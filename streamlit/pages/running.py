import streamlit as st
import os
import sys
from sacred import Experiment
from sacred.observers import SqlObserver
from io import StringIO
import threading
import time
from jnpr.junos import Device, exception
import re
import pandas as pd
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root_dir = os.path.abspath(os.path.join(current_script_dir, '..', '..'))
utils_dir_path = os.path.join(project_root_dir, 'utils')
if utils_dir_path not in sys.path:
    sys.path.insert(0, utils_dir_path)
vnpt_v4_path = os.path.join(project_root_dir, 'src', 'VNPT.v4')
if vnpt_v4_path not in sys.path:
    sys.path.insert(0, vnpt_v4_path)
from streamlit_utils import *
import phase1_1
import phase1_2
import phase2_1
import phase2_2
import phase2_3
import phase2_4

ex = Experiment("provision_pipeline", base_dir=".")
def run_experiment(ex, config_updates, logger, stop_event, phase):
    sys.stdout = TimestampStdoutWrapper(sys.__stdout__, logger)
    try:
        ex.run(command_name=f"run_phase{phase.replace('.','_')}", config_updates=config_updates)
    except Exception as e:
        print(f"[run_experiment] Error: {e}")
    finally:
        sys.stdout = sys.__stdout__
        stop_event.set()

@ex.command
def run_phase1_1(hopdong, ip, mapping, output_dir, database_name, template, ip_sheet, mapping_sheet, wipe_atp, signning, signning_sheet):
    ex.observers = [sql_observer]
    print("[run_phase1_1] Starting...")
    try:
        bbbg = phase1_1.parse_BBBG(hopdong)
        ip_df, mapping_df = phase1_1.parse_mapping(ip, mapping, output_dir, mapping_sheet, ip_sheet)
        sign_df=phase1_1.parse_signning(signning_file=signning, signning_sheet=signning_sheet, header_index=2)
        phase1_1.save_sqlite(output_dir, database_name, bbbg, ip_df, mapping_df, sign_df)
        phase1_1.generate_atp(template, output_dir, hopdong.split("/")[-1], database_name, hopdong)
        print('Done')
        return 1
    except Exception as e:
        print("[run_phase1_1] Error occurred during execution::: {}".format(e))
        return 0

@ex.command
def run_phase1_2(planningSN, planningSN_sheet, output_dir, database_name, hopdong):
    ex.observers = [sql_observer]
    print("[run_phase1_2] Starting...")
    try:
        phase1_2.process_slot_planning(planningSN, output_dir, database_name, hopdong, planningSN_sheet)
        return 1
    except Exception as e:
        print("[run_phase1_2] Error occurred during execution::: {}".format(e))
        return 0

@ex.command
def run_phase2_1(hopdong, list_bbbg, username, password, output_dir, database_name):
    ex.observers = [sql_observer]
    print("[run_phase2_1] Starting...")
    try:
        conn = sqlite3.connect(os.path.join(output_dir, database_name))
        cursor = conn.cursor()
        for bbbg in list_bbbg:
            print("----------------------Check serial-number for "+bbbg+'-----------------------')
            hostList=pd.read_sql_query("SELECT Hostname, IP, tail FROM 'BBBG' where tail=(?) and ma_HD=(?)", conn, params=(bbbg,hopdong))
            checkSNTable=pd.read_sql_query("SELECT * FROM 'checkSN' where BBBG=(?) and ma_HD=(?)" , conn, params=(bbbg,hopdong))
            hardwareList=pd.DataFrame()
            hostList=hostList.drop_duplicates()
            for index,row in hostList.iterrows():
                t=1
                while t<=6:
                    try:
                        if t>5:
                            print(row['IP']+" operation X exceed 5 retry, exiting")
                            break
                        print("connect to "+row['IP'])
                        netConf=phase2_1.NetConf(row['IP'], username, password)
                        deviceHardware=phase2_1.CheckSn(netConf, row['Hostname'])
                        netConf.close()
                        hardwareList=pd.concat([hardwareList, deviceHardware], axis=0)
                        if deviceHardware is not None:
                            break
                    except exception.ConnectError as err:
                        t+=1
                        print(err)
                        continue
                    except Exception as err:
                        netConf.close()
                        t+=1
                        print(err)
            if not hardwareList.empty:
                print("Compare database and device information")
                hardware_result=pd.merge(checkSNTable, hardwareList[['sn','slot','hostname']],  how='left', left_on=['SN'], right_on = ['sn'])
                hardware_result=phase2_1.update_host(hardware_result)
                hardware_result=phase2_1.update_installation_state(hardware_result)
                hardware_result=hardware_result.drop(columns=['hostname','slot','sn'])
                for index, row in hardware_result.iterrows():
                    cursor.execute('UPDATE "checkSN" SET TestStatus=?, InstallationStatus=?, RealSlot=?, Hostname=?, SN_status_update_timestamp=?, StatusTestStatus=? WHERE BBBG=? and SN=? and ma_HD=?', [row['TestStatus'], row['InstallationStatus'], row['RealSlot'],row['Hostname'], row['SN_status_update_timestamp'], row['StatusTestStatus'], row['BBBG'], row['SN'], hopdong])
                conn.commit()
                print("Updated databse successfully")
            else:
                print("No compared slot in "+bbbg)
        cursor.close()
        conn.close()
        return 1
    except Exception as e:
        print("[run_phase2_1] Error occurred during execution::: {}".format(e))
        return 0

@ex.command
def run_phase2_2(hopdong, hostname, hostslot, username, password, request_reboot, output_dir, database_name):
    try:
        database=os.path.join(output_dir,database_name)
        conn = sqlite3.connect(database)
        host=pd.read_sql_query("SELECT * FROM 'BBBG' where Hostname=(?) and ma_HD=(?)" , conn, params=(hostname,hopdong)).iloc[0]
        bbbg=host['tail']
        IpHost=host["IP"]
        pre_file_name=bbbg+'_'+hostname+'_'
        for item in hostslot:
            hw_type=item.split(' - ')[1].split(' ')[0]
            if hw_type!='chassis':
                slot=re.search("Slot (.*)",item.split(' - ')[2]).group(1)
                print("CHECK REBOOT: "+hopdong+' - '+IpHost+' - Slot '+slot)
            else:
                sn=re.search("chassis (.*)",item.split(' - ')[1]).group(1)
                print("CHECK REBOOT: "+hopdong+' - '+IpHost+' - Chassis SN '+sn)
            hostNamDev=username+"@"+hostname+"> "
            print("The first step\r\n")
            log_dir=os.path.join(output_dir,hopdong, "RAW LOG")
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            if hw_type=='fpc':
                phase2_2.FirstStepFPC(hostname, pre_file_name,IpHost, username, password, conn, slot, hopdong, request_reboot,hostNamDev,log_dir)
            elif hw_type=='module':
                phase2_2.FirstStepModule(hostname, pre_file_name,IpHost, username, password, conn, slot, hopdong,hostNamDev,log_dir)
            elif hw_type=='lca':
                phase2_2.FirstStepLCA(hostname, pre_file_name,IpHost, username, password, conn, slot, hopdong,hostNamDev,log_dir)
            elif hw_type=='chassis':
                phase2_2.FirstStepChassis(hostname, pre_file_name, IpHost, username, password, conn, sn, hopdong, request_reboot, hostNamDev,log_dir)
        conn.close()
        return 1
    except Exception as e:
        print("[run_phase2_2] Error occurred during execution::: {}".format(e))
        return 0

@ex.command
def run_phase2_3(hopdong, list_bbbg, output_dir, database_name):
    try:
        bbbg_on_db = get_list_time_bbbg(database=os.path.join(output_dir, database_name), list_bbbg=list_bbbg, hd=hopdong)
        bbbg_on_db['Ngày kết thúc'] = bbbg_on_db['Ngày kết thúc'].apply(pd.to_datetime, errors='coerce')
        bbbg_on_db['Thời gian ký'] = bbbg_on_db['Thời gian ký'].apply(pd.to_datetime, errors='coerce')
        for bbbg in list_bbbg:
            bbbg_info=bbbg_on_db[bbbg_on_db['tail'] == bbbg].iloc[0]
            phase2_3.export_atp(bbbg,hopdong,output_dir, bbbg_info['Ngày kết thúc'], bbbg_info['Thời gian ký'])
        return 1
    except Exception as e:
        print("[run_phase2_3] Error occurred during execution::: {}".format(e))
        return 0

@ex.command
def run_phase2_4(hopdong, template, output_dir, database_name):
    ex.observers = [sql_observer]
    print("[run_phase2_4] Starting...")
    try:
        phase2_4.generating_atp_appearance(hopdong, output_dir, database_name, template)
        return 1
    except Exception as e:
        print("[run_phase2_4] Error occurred during execution::: {}".format(e))
        return 0

if ('running' in st.session_state and st.session_state.running) or 'run_id' in st.query_params:
    conf = read_conf()
    log_db_path = os.path.join(conf['OUTPUT_DIR'], conf['DB_LOG'])
    sql_observer = SqlObserver(f"sqlite:///{os.path.abspath(log_db_path)}")
    if 'running' in st.session_state and st.session_state.running:
        st.header(f"Runing Job Phase {st.session_state.running_job}")
    elif 'run_id' in st.query_params:
        run_data=get_a_run(log_db_path, st.query_params['run_id'])
        phase=re.search(r'run_phase(\d+_\d+)', run_data['command']).group(1).replace('_','.')
        st.header(f"Runned Job #{st.query_params['run_id']} Phase {phase}")
    input_container, padding, output_container = st.columns([3, 0.2, 6.8])
    with input_container:
        st.subheader("Input")
        if 'running' in st.session_state and st.session_state.running:
            create_input_component(
                phase=st.session_state.running_job,
                input_vars=conf['input_vars'][st.session_state.running_job],
                values=st.session_state['input_data_phase_' + st.session_state.running_job]
            )
            create_sheet_components(conf['input_vars'][st.session_state.running_job], st.session_state.running_job, st.session_state['input_data_phase_' + st.session_state.running_job])
        elif 'run_id' in st.query_params:
            create_input_component(phase=phase, input_vars=conf['input_vars'][phase], values=clean_config(run_data['config']))
            create_sheet_components(input_vars=conf['input_vars'][phase], phase=phase, value=clean_config(run_data['config']))
    with output_container:
        st.subheader("Output")
        log_placeholder = st.empty()
        if not 'stop_event' in st.session_state:
            st.session_state.stop_event = threading.Event()
        tmp_output_dir = os.path.join(conf['TEMP_EXTRACT_HD'], 'extracted')
        if 'running' in st.session_state and st.session_state.running:
            if not st.session_state.current_running:
                st.session_state.current_running=True
                if st.session_state.running_job == '1.1':
                    ex.observers = [sql_observer]
                    base_name, file_extension = os.path.splitext(st.session_state['input_data_phase_1.1']['hopdong'].name)
                    DELETE_DIR(tmp_output_dir)
                    CREATE_EXPORT_DIR(tmp_output_dir)
                    if file_extension == '.tar':
                        extract_tar(st.session_state['input_data_phase_1.1']['hopdong'].getvalue(), tmp_output_dir)
                    elif file_extension == '.tar.gz' or file_extension == '.tgz':
                        extract_tar_gz(st.session_state['input_data_phase_1.1']['hopdong'].getvalue(), tmp_output_dir)
                    elif file_extension == '.zip':
                        extract_zip(st.session_state['input_data_phase_1.1']['hopdong'].getvalue(), tmp_output_dir)
                    elif file_extension == '.rar':
                        extract_rar(st.session_state['input_data_phase_1.1']['hopdong'].getvalue(), tmp_output_dir)
                    else:
                        raise ValueError(f"Unsupported file extension: {file_extension}")
                    file_uploaded={}
                    for i in ['ip', 'mapping', 'signning', 'template']:
                        if i in st.session_state['input_data_phase_1.1'] and st.session_state['input_data_phase_1.1'][i] is not None:
                            file_uploaded[i]=os.path.join(tmp_output_dir, st.session_state['input_data_phase_1.1'][i].name)
                            with open(file_uploaded[i], "wb") as f:
                                f.write(st.session_state['input_data_phase_1.1'][i].getbuffer())
                    file_name = os.path.basename(base_name)
                    output_dir = os.path.join(conf['OUTPUT_DIR'], file_name)
                    if st.session_state['input_data_phase_1.1']['wipe_atp'] and os.path.exists(os.path.join(output_dir, 'ATP')):
                        DELETE_DIR(os.path.join(output_dir, 'ATP'))
                    for f in [output_dir, os.path.join(output_dir, 'ATP'), os.path.join(output_dir, 'ATP Template'), os.path.join(output_dir, 'RAW LOG')]:
                        CREATE_EXPORT_DIR(f)
                    config_updates = {
                        "hopdong": os.path.join(tmp_output_dir, file_name),
                        "ip": file_uploaded['ip'],
                        "mapping": file_uploaded['mapping'],
                        "output_dir": conf['OUTPUT_DIR'],
                        "database_name": conf['DB_NAME'],
                        "template": file_uploaded['template'],
                        "ip_sheet": st.session_state['input_data_phase_1.1']['ip_sheet'],
                        "mapping_sheet": st.session_state['input_data_phase_1.1']['mapping_sheet'],
                        'wipe_atp': st.session_state['input_data_phase_1.1']['wipe_atp'],
                        'signning': file_uploaded['signning'] if 'signning' in file_uploaded else None,
                        'signning_sheet': st.session_state['input_data_phase_1.1']['signning_sheet'] if 'signning_sheet' in st.session_state['input_data_phase_1.1'] else None,
                    }
                elif st.session_state.running_job == '1.2':
                    ex.observers = [sql_observer]
                    file_planning=os.path.join(tmp_output_dir, st.session_state['input_data_phase_1.2']['planningSN'].name)
                    with open(file_planning, "wb") as f:
                        f.write(st.session_state['input_data_phase_1.2']['planningSN'].getbuffer())
                    config_updates={
                        "output_dir": conf['OUTPUT_DIR'],
                        "database_name": conf['DB_NAME'],
                        "planningSN": file_planning,
                        "planningSN_sheet": st.session_state['input_data_phase_1.2']['planningSN_sheet'],
                        "hopdong": st.session_state['input_data_phase_1.2']['hopdong'],
                    }
                elif st.session_state.running_job == '2.1':
                    ex.observers = [sql_observer]
                    config_updates={
                        "output_dir": conf['OUTPUT_DIR'],
                        "database_name": conf['DB_NAME'],
                        "password": st.session_state['input_data_phase_2.1']['password'],
                        "username": st.session_state['input_data_phase_2.1']['username'],
                        "list_bbbg": st.session_state['input_data_phase_2.1']['list_bbbg'],
                        "hopdong": st.session_state['input_data_phase_2.1']['hopdong'],
                    }
                elif st.session_state.running_job == '2.2':
                    ex.observers = [sql_observer]
                    config_updates={
                        "output_dir": conf['OUTPUT_DIR'],
                        "database_name": conf['DB_NAME'],
                        "password": st.session_state['input_data_phase_2.2']['password'],
                        "username": st.session_state['input_data_phase_2.2']['username'],
                        "hostname": st.session_state['input_data_phase_2.2']['hostname'],
                        "hopdong": st.session_state['input_data_phase_2.2']['hopdong'],
                        "hostslot": st.session_state['input_data_phase_2.2']['hostslot'],
                        "request_reboot": 'YES' if st.session_state['input_data_phase_2.2']['request_reboot'] else 'NO',
                    }
                elif st.session_state.running_job == '2.3':
                    ex.observers = [sql_observer]
                    config_updates={
                        "output_dir": conf['OUTPUT_DIR'],
                        "database_name": conf['DB_NAME'],
                        "list_bbbg": st.session_state['input_data_phase_2.3']['list_bbbg'],
                        "hopdong": st.session_state['input_data_phase_2.3']['hopdong'],
                    }
                elif st.session_state.running_job == '2.4':
                    file_template=''
                    if 'template' in st.session_state['input_data_phase_2.4'] and st.session_state['input_data_phase_2.4']['template'] is not None:
                        file_template=os.path.join(tmp_output_dir, st.session_state['input_data_phase_2.4']['template'].name)
                        with open(file_template, "wb") as f:
                            f.write(st.session_state['input_data_phase_2.4']['template'].getbuffer())
                    ex.observers = [sql_observer]
                    config_updates={
                        "output_dir": conf['OUTPUT_DIR'],
                        "database_name": conf['DB_NAME'],
                        "template": file_template,
                        "hopdong": st.session_state['input_data_phase_2.4']['hopdong'],
                    }
                thread = threading.Thread(target=run_experiment, args=(ex, config_updates, st.session_state.logger, st.session_state.stop_event, st.session_state.running_job))
                thread.start()
            else:
                pass
            # Periodically update the UI while the thread is running
            while not st.session_state.stop_event.is_set():
                time.sleep(0.1)  # Adjust the refresh rate as needed
                html = show_scrollable_log(st.session_state.logger.get_html(), 70)
                log_placeholder.markdown(html, unsafe_allow_html=True)

            html = show_scrollable_log(st.session_state.logger.get_html(), 70)
            log_placeholder.markdown(html, unsafe_allow_html=True)
            del st.session_state['stop_event']
            st.session_state.running = False
        elif 'run_id' in st.query_params:
            log_content = run_data['captured_out']
            html = show_scrollable_log(log_content, 70)
            log_placeholder.markdown(html, unsafe_allow_html=True)
            # Ensure the final log output is displaye
