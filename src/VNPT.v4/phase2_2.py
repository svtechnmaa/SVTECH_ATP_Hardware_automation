import os
import re
import pandas as pd
import time
from datetime import datetime, timedelta
from docx.shared import Pt
import logging
from jnpr.junos import Device, exception
import sqlite3
import argparse
import random
import sys
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root_dir = os.path.abspath(os.path.join(current_script_dir, '..', '..'))
utils_dir_path = os.path.join(project_root_dir, 'utils')
if utils_dir_path not in sys.path:
    sys.path.insert(0, utils_dir_path)
from module_utils import *

class MaxRetriesExceeded(Exception):
    """Raised when an operation exceeds its maximum allowed retries."""
    pass

def NetConf(host, username, password):
    print("Netconf")
    NetConfSsh = Device(host=host, user=username, passwd=password, port=22)
    NetConfSsh.open()
    if NetConfSsh.connected == True:
        print("connected to device")
        return NetConfSsh
    else:
        print("NetConf SSH open but cannot connected to device")
        logging.exception("NetConf SSH open but cannot connected to device")
        return None

def CheckSn(netConf,hw_type):
    print("checkSN")
    device_hardware =pd.DataFrame()
    if hw_type=='fpc':
        device_hardware = GET_PYEZ_TABLEVIEW_FORMATTED(dev=netConf,tableview_file=os.path.join(current_script_dir, '../hardwareTable.yml'),data_type='FPC', include_hostname=False,output_format='dataframe')
        device_hardware["slot"]=device_hardware['hardware_name'].apply(lambda x: str(re.search("FPC (\d+)",x).group(1)))
    elif hw_type=='module':
        device_hardware = GET_PYEZ_TABLEVIEW_FORMATTED(dev=netConf,tableview_file=os.path.join(current_script_dir, '../hardwareTable.yml'),data_type='Module', include_hostname=False,output_format='dataframe')
        device_hardware["slot"] = device_hardware.apply(lambda x: str(x['fpc_slot'].replace(r'FPC ', ''))+'/'+str(x['pic_slot'].replace(r'PIC ', ''))+'/'+str(x['hardware_name'].replace(r'Xcvr ', '')), axis=1)
    elif hw_type=='lca':
        device_hardware = GET_PYEZ_TABLEVIEW_FORMATTED(dev=netConf,tableview_file=os.path.join(current_script_dir, '../hardwareTable.yml'),data_type='LCA', include_hostname=False,output_format='dataframe')
        device_hardware["slot"]=device_hardware['hardware_name'].apply(lambda x: str(re.search("ADC (\d+)",x).group(1)))
    elif hw_type=='chassis':
        device_hardware = GET_PYEZ_TABLEVIEW_FORMATTED(dev=netConf,tableview_file=os.path.join(current_script_dir, '../hardwareTable.yml'),data_type='Chassis', include_hostname=False,output_format='dataframe')
    device_hardware=device_hardware.drop(columns=['tableview_key',])
    return device_hardware

def compare_db_and_pyez(planning_data, real_data, slot):
    print("Compare database with host")
    planning_data["RealSlot"] = planning_data["RealSlot"].apply(lambda x: float(x) if isinstance(x, (int, float)) or str(x).replace('.','',1).isdigit() else str(x))
    real_data["slot"] = real_data["slot"].apply(lambda x: float(x) if isinstance(x, (int, float)) or str(x).replace('.','',1).isdigit() else str(x))
    result_data=pd.merge(planning_data[['SN','RealSlot','TestStatus','PartNumber']], real_data,  how='left', left_on=['SN','RealSlot'], right_on = ['sn',"slot"])
    if result_data['sn'].isnull().any() or result_data['slot'].isnull().any():
        print("Host has no matching slot "+slot)
        return pd.DataFrame()
    else:
        return result_data

def apply_command(netConf, command,step,HostName):
    if '| match' in command:
        based_command, filter = command.split('| match ')
        if '| no-more' in filter:
            filter = filter.split('| no-more')[0].strip().strip('"')
        elif '| no-more' in based_command:
            based_command = based_command.split('| no-more')[0]
        out_put = netConf.cli(based_command.strip(), warning= False)
        out_put="\n".join(line for line in out_put.splitlines() if filter in line)+'\n'
    else:
        out_put = netConf.cli(command, warning= False)
    time.sleep(5)
    # output=HostName+command+'\r'+str(pd.to_datetime(datetime.now()).strftime('%b %d %H:%M:%S'))+'\r'
    output=HostName+command+'\r'+out_put+'\r'
    print("Step "+ step+": Run command: "+command +"...OK")
    return output

def check_fpc_status(netConf,fpc_slot,step,HostName):
    print("Check fpc status")
    command = "show chassis fpc pic-status "+fpc_slot
    out_put = netConf.cli( command,format="json", warning= False)
    apply_command(netConf,command,step,HostName)
    fpc_data = out_put["fpc-information"][0]["fpc"][0]
    fpc_slot = fpc_data["slot"][0]["data"]
    fpc_state = fpc_data["state"][0]["data"]
    dict_pic = {}
    if 'pic' in fpc_data and len(fpc_data["pic"])>0 :
        for element in fpc_data["pic"]:
            pic_slot = element["pic-slot"][0]['data']
            pic_state = element["pic-state"][0]['data']
            dict_pic.update([("PIC "+pic_slot,pic_state)])
    return fpc_state, dict_pic

def get_module_in_fpc(netconf, slot):
    device_hardware = GET_PYEZ_TABLEVIEW_FORMATTED(dev=netconf,tableview_file=os.path.join(current_script_dir, '../hardwareTable.yml'),data_type='Module', include_hostname=False,output_format='dataframe')
    if isinstance(device_hardware, pd.DataFrame) and not device_hardware.empty:
        tempData = device_hardware.loc[device_hardware['fpc_slot'] == 'FPC '+slot]
        if not tempData.empty:
            tempData["slot"] = tempData.apply(lambda x: str(re.search("Xcvr (\d+)",x['hardware_name']).group(1)), axis=1)
            tempData['int']= tempData.apply(lambda x: str(x['fpc_slot'].replace(r'FPC ', ''))+'/'+str(x['pic_slot'].replace(r'PIC ', ''))+'/'+str(x['slot']), axis=1)
            return list(tempData['int'])
    return []

def get_master_RE(netconf):
    device_hardware = GET_PYEZ_TABLEVIEW_FORMATTED(dev=netconf,tableview_file=os.path.join(current_script_dir, '../hardwareTable.yml'),data_type='RE',output_format='dataframe')
    return device_hardware.loc[device_hardware['State'] == 'master'].iloc[0]['Slot']

def get_state_cb_sfb(netconf, type, slot):
    device_hardware = GET_PYEZ_TABLEVIEW_FORMATTED(dev=netconf,tableview_file=os.path.join(current_script_dir, '../hardwareTable.yml'),data_type=type.upper(), include_hostname=False,output_format='dataframe')
    # if isinstance(device_hardware, pd.DataFrame) and not device_hardware.empty:
    return device_hardware.loc[device_hardware['name'] == f'{type.upper()} {slot}'].iloc[0]['state']
    # device_hardware = GET_PYEZ_TABLEVIEW_FORMATTED(dev=netconf,tableview_file='../hardwareTable.yml',data_type=type.upper(), include_hostname=False,output_format='dataframe')
    # return device_hardware.iloc[0]['state']

def OnlineFpc(netConf, HostName, fpc_slot, fpc_sn, step):
    print("Step "+step+": Online MPC: ... Waiting")
    print("Step "+step+": Online MPC")
    command = "request chassis fpc slot "+fpc_slot+" online"
    fpc_state, dict_pic  = check_fpc_status(netConf,fpc_slot,"1.3",HostName)
    time.sleep(10)
    print("ONLINE FPC?request chassis fpc slot "+fpc_slot+" online\nSerial: "+fpc_sn+"\nState: "+fpc_state)
    output=apply_command(netConf,command,"1.3",HostName)
    return output

def RebootFpc(netConf,HostName, fpc_slot, fpc_sn,step):
    print("Step "+step+": Offline MPC: ... Waiting")
    command = "request chassis fpc slot "+fpc_slot+" offline"
    time.sleep(5)
    output=apply_command(netConf,command,"1.3",HostName)
    return output

def OnlineCB_SFB(netConf, type, slot, HostName, step):
    print(f"Step {step}: Online {type} {slot}: ... Waiting")
    return apply_command(netConf,f"request chassis {type} online slot {slot}",step,HostName)

def RebootCB_SFB(netConf, type, slot, HostName, step):
    print(f"Step {step}: Offline {type} {slot}: ... Waiting")
    return apply_command(netConf,f"request chassis {type} offline slot {slot}",step,HostName)

def update_db(conn_db, hostname, SN, status, hd):
    time_current=time.time()
    print("Update database")
    cursor = conn_db.cursor()
    cursor.execute('UPDATE "checkSN" SET SN_status_update_timestamp = ?, StatusTestStatus= ?, TestStatus = ? WHERE Hostname=? and SN=? and ma_HD=?', [time_current, 'Valid',status,hostname, SN,hd])
    conn_db.commit()
    print("Record Updated successfully")
    cursor.close()

def FirstStepFPC(hostname, pre_file_name, IpHost, UserName, PassWord, conn_db, slot, hd, request_reboot,hostNamDev,log_dir):
    list_commands_on_hd={
        '510-2024':{
            'before_reboot': ['show chassis hardware models', 'show chassis hardware', 'show chassis fpc', "show chassis fpc {fpc_slot} detail", "show chassis fpc pic-status {fpc_slot}",
                               "show chassis pic fpc-slot {fpc_slot} pic-slot 0", "show chassis pic fpc-slot {fpc_slot} pic-slot 1", "show interface terse media et-{fpc_slot}*", "show interfaces diagnostics optics et-{interface}"],
            'after_reboot': ["show chassis fpc {fpc_slot} detail", "show chassis fpc pic-status {fpc_slot}", "show interface terse media et-{fpc_slot}*"]
        },
        '389':{
            'before_reboot': ["show chassis hardware",'show chassis hardware models',"show chassis fpc","show chassis fpc {fpc_slot} detail","show chassis fpc pic-status {fpc_slot}",
                            "show chassis pic fpc-slot {fpc_slot} pic-slot 0", "show chassis pic fpc-slot {fpc_slot} pic-slot 1", "show interface terse media et-{fpc_slot}*"],
            'after_reboot': ["show chassis fpc {fpc_slot} detail", "show chassis fpc pic-status {fpc_slot}", "show interface terse media et-{fpc_slot}*"]
        },
        '126-2025':{
            'before_reboot': ["show chassis hardware models","show chassis hardware","show chassis fpc","show chassis fpc {fpc_slot} detail","show chassis fpc pic-status {fpc_slot}",
                            "show chassis pic fpc-slot {fpc_slot} pic-slot 0", "show chassis pic fpc-slot {fpc_slot} pic-slot 1", "show interface terse media et-{fpc_slot}*", "show interfaces diagnostics optics et-{interface}", "show interface terse media xe-{fpc_slot}*", "show interfaces diagnostics optics xe-{interface}"],
            'after_reboot': ["show chassis fpc {fpc_slot} detail", "show chassis fpc pic-status {fpc_slot}", "show interface terse media et-{fpc_slot}*","show interface terse media xe-{fpc_slot}*"]
        },
        '117-2025':{
            'before_reboot': ['show chassis hardware models', 'show chassis hardware', 'show chassis fpc', "show chassis fpc {fpc_slot} detail", "show chassis fpc pic-status {fpc_slot}",
                               "show chassis pic fpc-slot {fpc_slot} pic-slot 0", "show chassis pic fpc-slot {fpc_slot} pic-slot 1", "show interface terse media et-{fpc_slot}*", "show interfaces diagnostics optics et-{interface}"],
            'after_reboot': ["show chassis fpc {fpc_slot} detail", "show chassis fpc pic-status {fpc_slot}", "show interface terse media et-{fpc_slot}*"]
        },
        'default':{
            'before_reboot': ["show chassis hardware","show chassis fpc","show chassis fpc {fpc_slot} detail","show chassis fpc pic-status {fpc_slot}",
                            "show chassis pic fpc-slot {fpc_slot} pic-slot 0", "show chassis pic fpc-slot {fpc_slot} pic-slot 1", "show interface terse media et-{fpc_slot}*", "show interface terse media xe-{fpc_slot}*"],
            'after_reboot': ["show chassis fpc {fpc_slot} detail", "show chassis fpc pic-status {fpc_slot}", "show interface terse media et-{fpc_slot}*", "show interface terse media xe-{fpc_slot}*"]
        }
    }
    hd_commands=next((v for k, v in list_commands_on_hd.items() if k in hd), list_commands_on_hd['default'])
    ###Get list SN on device###
    t=1
    while t<=6:
        try:
            if t>5:
                logging.critical("operation X exceed 5 retry, exiting")
                print("operation X exceed 5 retry, exiting")
                raise MaxRetriesExceeded
            netConf=NetConf(IpHost, UserName, PassWord)
            print("First_step get list SN on host")
            device_hardware = CheckSn(netConf,'fpc')
            netConf.close()
            if device_hardware is not None:
                break
        except exception.ConnectError as err:
            t+=1
            print('Error connect to {}, {}'.format(IpHost,err))
            logging.exception('Error connect to {}, {}'.format(IpHost,err))
            continue
        except MaxRetriesExceeded as err:
            print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
            raise
        except Exception as err:
            netConf.close()
            t+=1
            print('Error check SN of {}, {}'.format(IpHost,err))
            logging.exception('Error check SN of {}, {}'.format(IpHost,err))
    planning_hardware=pd.read_sql_query("SELECT * FROM 'checkSN' where ma_HD=(?) and Hostname=(?) and Type='fpc' and RealSlot=(?) and (TestStatus='Installed' or TestStatus like 'Checked%')" , conn_db, params=(hd, hostname,slot))
    planning_time=pd.read_sql_query("""SELECT "Ngày kết thúc", "Thời gian ký" FROM BBBG WHERE ma_HD = ? AND Hostname = ?""", conn_db, params=(hd, hostname)).iloc[0]
    planning_time[["Ngày kết thúc", "Thời gian ký"]] = planning_time[["Ngày kết thúc", "Thời gian ký"]].apply(pd.to_datetime, errors='coerce')
    result_installed=compare_db_and_pyez(planning_hardware, device_hardware, slot)
    if result_installed.empty:
        logging.exception("Serial Number and Slot not matching with device")
        print("Serial Number and Slot not matching with device. Run phase 2.1 again")
        return
    ###Get SN status and online card if current status is offline###
    fpc_sn=result_installed.iloc[0]['sn']
    fpc_slot=str(int(result_installed.iloc[0]['slot']))
    new_status=result_installed.iloc[0]['TestStatus']
    t=1
    while t<=21:
        try:
            if t>20:
                print("operation X exceed 20 retry, exiting")
                logging.critical("operation X exceed 20 retry, exiting")
                raise MaxRetriesExceeded
            print("CHECK 1: check status FPC")
            netConf = NetConf(IpHost, UserName, PassWord)
            fpc_state, dict_pic = check_fpc_status(netConf,fpc_slot,"1.3",hostNamDev)
            if fpc_state == "Offline":
                print("CHECK 2: Online FPC")
                print("Step 1.1: FPC slot "+fpc_slot +" status is "+fpc_state)
                print("Alert !!! FPC slot "+fpc_slot+" is not ONLINE\n ONLINE to start ATP")
                OnlineFpc(netConf,hostNamDev, fpc_slot, fpc_sn,"1.1")
                time.sleep(10)
                netConf.close()
                continue
            elif fpc_state=="Online":
                print("Step 1.1: FPC slot "+fpc_sn +" status is "+fpc_state)
                netConf.close()
                break
            else:
                print("CHECK 3: Waiting FPC online")
                t+=1
                netConf.close()
                print("Step 1.1: FPC slot "+fpc_slot +" status is "+fpc_state)
                print("Step 1.1: Waiting 30s...Waiting")
                time.sleep(30)
        except MaxRetriesExceeded as err:
            print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
            raise
        except exception.ConnectError as err:
            t+=1
            print(err)
            logging.exception(err)
            time.sleep(3)
            continue
        except Exception as err:
            netConf.close()
            t+=1
            print(err)
            logging.exception(err)
            time.sleep(3)
    ###Get PIC status and check all PIC is online###
    t=1
    while t<=31:
        try:
            if t>30:
                print("operation X exceed 30 retry, exiting")
                logging.critical("operation X exceed 30 retry, exiting")
                raise MaxRetriesExceeded
            print("CHECK 4: check status PIC")
            netConf = NetConf(IpHost, UserName, PassWord)
            fpc_state, dict_pic = check_fpc_status(netConf,fpc_slot,"1.1",hostNamDev)
            netConf.close()
            if dict_pic!={} and all(dict_pic[pic_slot] =="Online" for pic_slot in dict_pic):
                for pic in dict_pic:
                    print("Step 1.1: "+pic +" status is "+dict_pic[pic])
                break
            elif dict_pic!={}:
                for pic in dict_pic:
                    print("Step 1.1: "+pic +" status is "+dict_pic[pic])
            t+=1
            print("Step 1.1: All PIC not ONLINE wait 20s...Waiting")
            time.sleep(20)
        except MaxRetriesExceeded as err:
            print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
            raise
        except exception.ConnectError as err:
            t+=1
            print(err)
            logging.exception(err)
            time.sleep(3)
            continue
        except Exception as err:
            netConf.close()
            t+=1
            print(err)
            logging.exception(err)
            time.sleep(3)

    ###Collect output command before reboot###
    result_write_file=""
    t=1
    while t<=6:
        try:
            if t>5:
                print("operation X exceed 5 retry, exiting")
                logging.critical("operation X exceed 5 retry, exiting")
                raise MaxRetriesExceeded
            print("CHECK 5: get command output to ATP")
            netConf = NetConf(IpHost, UserName, PassWord)
            result_show=""
            print("Step 1.2: raw log: ... Waiting")
            list_interface=get_module_in_fpc(netConf,fpc_slot)
            for command in hd_commands['before_reboot']:
                if '{fpc_slot}' in command:
                    command=command.format(fpc_slot=fpc_slot)
                if 'diagnostics' in command and list_interface:
                    for i in list_interface:
                        result_show+=apply_command(netConf,command.format(interface=i),"1.2",hostNamDev)
                elif ('terse media' in command and list_interface) or ('terse media' not in command and 'diagnostics' not in command):
                    result_show+=apply_command(netConf, command, "1.2",hostNamDev)
            print("Step 1.2: Done: ... Complete")
            netConf.close()
            if result_show!='':
                result_write_file+=result_show
                break
        except MaxRetriesExceeded as err:
            print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
            raise
        except exception.ConnectError as err:
            t+=1
            print(err)
            logging.exception(err)
            time.sleep(3)
            continue
        except Exception as err:
            netConf.close()
            t+=1
            print(err)
            logging.exception(err)
            time.sleep(3)

    if request_reboot=="NO":
        new_status="Checked without reboot"
        result_write_file+=hostNamDev+"User select no reboot\n"
    elif request_reboot=="YES":
        new_status="Checked with reboot"
    #2.2.3. Perform on/off operation
        print("Step 1.3: Offline & Online MPC: ... Waiting")
        print("Step 1.3: Slot "+fpc_slot+" on device SN is "+fpc_sn)
        t=1
        while t<=21:
            try:
                if t>20:
                    print("operation X exceed 20 retry, exiting")
                    logging.critical("operation X exceed 20 retry, exiting")
                    raise MaxRetriesExceeded
                print("CHECK 6: check FPC status")
                netConf = NetConf(IpHost, UserName, PassWord)
                fpc_state, dict_pic = check_fpc_status(netConf,fpc_slot,"1.3",hostNamDev)
                if fpc_state == "Online":
                    print("Step 1.3: FPC slot "+fpc_slot +" status is "+fpc_state)
                    result_show= RebootFpc(netConf,hostNamDev,fpc_slot,fpc_sn,"1.3")
                    netConf.close()
                    time.sleep(5)
                    continue
                #netConf.close()
                elif fpc_state == "Offline":
                    print("Step 1.3: FPC slot "+fpc_slot +" status is "+fpc_state)
                    result_write_file+=result_show
                    netConf.close()
                    break
                else:
                    t+=1
                    netConf.close()
                    print("Step 1.3: FPC slot "+fpc_slot +" status is "+fpc_state)
                    print("Step 1.3: Waiting 30s...Waiting")
                    time.sleep(30)
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)
                continue
            except Exception as err:
                netConf.close()
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)

        print("CHECK 7: show chassis fpc")
        t=1
        while t<=6:
            try:
                if t>5:
                    print("operation X exceed 5 retry, exiting")
                    logging.critical("operation X exceed 5 retry, exiting")
                    raise MaxRetriesExceeded
                result_show=""
                netConf = NetConf(IpHost, UserName, PassWord)
                result_show= apply_command(netConf,"show chassis fpc","1.3",hostNamDev)
                netConf.close()
                if result_show!='':
                    result_write_file+=result_show
                    break
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                t+=1
                print(err)
                logging.exception(err)
                time.sleep(3)
                continue
            except Exception as err:
                netConf.close()
                t+=1
                print(err)
                logging.exception(err)
                time.sleep(3)

        print("Step 1.3: Slot "+fpc_slot+" on device SN is "+fpc_sn)
        t=1
        while t<=21:
            try:
                if t>20:
                    print("operation X exceed 20 retry, exiting")
                    logging.critical("operation X exceed 20 retry, exiting")
                    raise MaxRetriesExceeded
                print("CHECK 8: Online FPC")
                netConf = NetConf(IpHost, UserName, PassWord)
                fpc_state, dict_pic = check_fpc_status(netConf,fpc_slot,"1.3",hostNamDev)
                if fpc_state == "Offline":
                    print("Step 1.3: FPC slot "+fpc_slot +" status is "+fpc_state)
                    result_show= OnlineFpc(netConf,hostNamDev,fpc_slot,fpc_sn,"1.3")
                    netConf.close()
                    time.sleep(10)
                    continue
                elif fpc_state=="Online":
                    print("Step 1.3: FPC slot "+fpc_slot +" status is "+fpc_state)
                    result_write_file+=result_show
                    netConf.close()
                    break
                else:
                    t+=1
                    netConf.close()
                    print("Step 1.3: FPC slot "+fpc_slot +" status is "+fpc_state)
                    print("Step 1.3: Waiting 30s...Waiting")
                    time.sleep(30)
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)
                continue
            except Exception as err:
                netConf.close()
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)
        t=1
        while t<=31:
            try:
                if t>30:
                    print("operation X exceed 30 retry, exiting")
                    logging.critical("operation X exceed 30 retry, exiting")
                    raise MaxRetriesExceeded
                print("CHECK 9: Online PIC")
                netConf = NetConf(IpHost, UserName, PassWord)
                fpc_state, dict_pic = check_fpc_status(netConf,fpc_slot,"1.1",hostNamDev)
                netConf.close()
                if dict_pic!={} and all(dict_pic[pic_slot] =="Online" for pic_slot in dict_pic):
                    for pic in dict_pic:
                        print("Step 1.3: "+pic +" status is "+dict_pic[pic])
                    break
                elif dict_pic!={}:
                    for pic in dict_pic:
                        print("Step 1.3: "+pic +" status is "+dict_pic[pic])
                t+=1
                print("Step 1.1: All PIC not ONLINE wait 20s...Waiting")
                time.sleep(20)
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)
                continue
            except Exception as err:
                netConf.close()
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)

        print("CHECK 10: get chassis fpc")
        t=1
        while t<=6:
            try:
                if t>5:
                    print("operation X exceed 5 retry, exiting")
                    logging.critical("operation X exceed 5 retry, exiting")
                    raise MaxRetriesExceeded
                netConf = NetConf(IpHost, UserName, PassWord)
                result_show= apply_command(netConf,"show chassis fpc","1.3",hostNamDev)
                netConf.close()
                if result_show:
                    result_write_file+=result_show
                    break
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                t+=1
                print(err)
                logging.exception(err)
                time.sleep(3)
                continue
            except Exception as err:
                netConf.close()
                t+=1
                print(err)
                logging.exception(err)
                time.sleep(3)
    #2.2.3. record additional log after ATP
        t=1
        while t<=6:
            try:
                if t>5:
                    print("operation X exceed 5 retry, exiting")
                    logging.critical("operation X exceed 5 retry, exiting")
                    raise MaxRetriesExceeded
                print("CHECK 11: get command output to ATP")
                result_show=""
                netConf = NetConf(IpHost, UserName, PassWord)
                for command in hd_commands['after_reboot']:
                    if '{fpc_slot}' in command:
                        command=command.format(fpc_slot=fpc_slot)
                    if ('terse media' in command and list_interface) or ('terse media' not in command):
                        result_show+=apply_command(netConf,command,"1.3",hostNamDev)
                netConf.close()
                if result_show!='':
                    result_write_file+=result_show
                    break
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)
                continue
            except Exception as err:
                netConf.close()
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)

    print("Step 2.1: Power on chassis. Insert MPC into chassis, verify Linecards are present:... waiting")
    if '510-2024' in hd or '117-2025' in hd:
        list_command = ["show chassis hardware models","show system license"]
    else:
        list_command = ["show chassis hardware","show system license"]
    t=1
    while t<=6:
        try:
            if t>5:
                print("operation X exceed 5 retry, exiting")
                logging.critical("operation X exceed 5 retry, exiting")
                raise MaxRetriesExceeded
            print("CHECK 12: get command output to ATP")
            result_show=""
            netConf=NetConf(IpHost, UserName, PassWord)
            for command in list_command:
                result_show+=apply_command(netConf,command,"2.1",hostNamDev)
            netConf.close()
            if result_show!='':
                result_write_file+=result_show
                break
        except MaxRetriesExceeded as err:
            print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
            raise
        except exception.ConnectError as err:
            t+=1
            print(err)
            logging.exception(err)
            time.sleep(3)
            continue
        except Exception as err:
            netConf.close()
            t+=1
            print(err)
            logging.exception(err)
            time.sleep(3)

    print("Step 1.3: Writing raw log file")
    # with open(os.path.join(log_dir,pre_file_name+"FPC "+fpc_slot+".txt"),"w") as outfile:
    with open(os.path.join(log_dir,pre_file_name+"FPC "+fpc_sn+".txt"),"w") as outfile:
        outfile.write(result_write_file)
    print("Done writing raw log")
    print("Update db")
    update_db(conn_db, hostname, fpc_sn,new_status, hd)

def FirstStepModule(hostname, pre_file_name, IpHost, UserName, PassWord, conn_db, slot, hd,hostNamDev,log_dir):
    list_commands_on_hd={
        '510-2024':{
            "commands": ['show chassis hardware models', 'show chassis hardware', "show interface terse media et-{card}*", "show interfaces diagnostics optics {int}-{module}"]
        },
        '126-2025':{
            'commands': ['show chassis hardware models', 'show chassis hardware', "show interface terse media et-{card}*", 'show interfaces diagnostics optics et-{module}', "show interface terse media xe-{card}*", 'show interfaces diagnostics optics xe-{module}']
        },
        'default':{
            "commands": ['show chassis hardware', "show interfaces diagnostics optics {int}-{module}"]
        }
    }
    t=1
    list_command=next((v['commands'] for k, v in list_commands_on_hd.items() if k in hd), list_commands_on_hd['default']['commands'])
    while t<=6:
        try:
            if t>5:
                print("operation X exceed 5 retry, exiting")
                logging.critical("operation X exceed 5 retry, exiting")
                raise MaxRetriesExceeded
            netConf=NetConf(IpHost, UserName, PassWord)
            print("First_step get list SN on host")
            device_hardware = CheckSn(netConf,'module')
            netConf.close()
            if device_hardware is not None:
                break
        except MaxRetriesExceeded as err:
            print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
            raise
        except exception.ConnectError as err:
                t+=1
                print('Error connect to {}, {}'.format(IpHost,err))
                logging.exception('Error connect to {}, {}'.format(IpHost,err))
                continue
        except Exception as err:
                netConf.close()
                t+=1
                logging.exception('Error check SN of {}, {}'.format(IpHost,err))
                print('Error check SN of {}, {}'.format(IpHost,err))
    planning_hardware=pd.read_sql_query("SELECT * FROM 'checkSN' where ma_HD=(?) and Hostname=(?) and Type='module' and RealSlot=(?) and TestStatus in ('Installed', 'Checked')" , conn_db, params=(hd, hostname,slot))
    result_installed=compare_db_and_pyez(planning_hardware, device_hardware, slot)
    if result_installed.empty:
        logging.exception("Serial Number and Slot not matching with device")
        print("Serial Number and Slot not matching with device. Run phase 2.1 again")
        return

    module_sn=result_installed.iloc[0]['sn']
    module_slot=str(result_installed.iloc[0]['slot'])
    new_status=result_installed.iloc[0]['TestStatus']
    module_throughput=result_installed.iloc[0]['PartNumber']
    #2.2.2. Collect FPC/PIC log
    t=1
    while t<=6:
        try:
            if t>5:
                print("operation X exceed 5 retry, exiting")
                logging.critical("operation X exceed 5 retry, exiting")
                raise MaxRetriesExceeded
            print("CHECK 1: get command output to ATP")
            netConf = NetConf(IpHost, UserName, PassWord)
            print("Step 1.2: raw log: ... Waiting")
            result_write_file=""
            int_check='xe' if module_throughput.strip().startswith(('XFP','SFPP')) else \
                 'et' if module_throughput.strip().startswith(('QSFP','QDD')) else \
                 'ge' if module_throughput.strip().startswith('SFP') else None
            for command in list_command:
                result_write_file+=apply_command(netConf, command.format(card=str(module_slot.split('/')[0]), int=int_check, module=module_slot), "1.2",hostNamDev)
            netConf.close()
            if result_write_file!="":
                print("Step 1.2: Done: ... Complete")
                print("Step 1.2: Writing file log 1_2.txt: ... writing")
                # with open(os.path.join(log_dir,pre_file_name+"Module "+module_slot.replace("/", ".")+".txt"),"w") as outfile:
                with open(os.path.join(log_dir,pre_file_name+"Module "+module_sn+".txt"),"w") as outfile:
                    outfile.write(result_write_file)
                print("Step 1.2:Writing log 1_2.txt: ... complete")
                new_status="Checked"
                break
        except MaxRetriesExceeded as err:
            print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
            raise
        except exception.ConnectError as err:
            t+=1
            logging.exception(err)
            print(err)
            time.sleep(3)
            continue
        except Exception as err:
            netConf.close()
            t+=1
            logging.exception(err)
            print(err)
            time.sleep(3)
    update_db(conn_db, hostname, module_sn,new_status, hd)

def FirstStepLCA(hostname, pre_file_name, IpHost, UserName, PassWord, conn_db, slot, hd,hostNamDev,log_dir):
    t=1
    while t<=6:
        try:
            if t>5:
                print("operation X exceed 5 retry, exiting")
                logging.critical("operation X exceed 5 retry, exiting")
                raise MaxRetriesExceeded
            netConf=NetConf(IpHost, UserName, PassWord)
            print("First_step get list SN on host")
            device_hardware = CheckSn(netConf,'lca')
            netConf.close()
            if device_hardware is not None:
                break
        except MaxRetriesExceeded as err:
            print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
            raise
        except exception.ConnectError as err:
                t+=1
                logging.exception('Error connect to {}, {}'.format(IpHost,err))
                print('Error connect to {}, {}'.format(IpHost,err))
                continue
        except Exception as err:
                netConf.close()
                t+=1
                logging.exception('Error check SN of {}, {}'.format(IpHost,err))
                print('Error check SN of {}, {}'.format(IpHost,err))
    planning_hardware=pd.read_sql_query("SELECT * FROM 'checkSN' where ma_HD=(?) and Hostname=(?) and Type='lca' and RealSlot=(?) and TestStatus in ('Installed', 'Checked')" , conn_db, params=(hd,hostname,slot))
    result_installed=compare_db_and_pyez(planning_hardware, device_hardware, slot)
    if result_installed.empty:
        logging.exception("Serial Number and Slot not matching with device")
        print("Serial Number and Slot not matching with device. Run phase 2.1 again")
        return
    lca_sn=result_installed.iloc[0]['sn']
    t=1
    while t<=6:
        try:
            if t>5:
                print("operation X exceed 5 retry, exiting")
                logging.critical("operation X exceed 5 retry, exiting")
                raise MaxRetriesExceeded
            print("CHECK 1: get command output to ATP")
            netConf = NetConf(IpHost, UserName, PassWord)
            print("Step 1.2: raw log: ... Waiting")
            list_command = ["show chassis hardware",'show chassis hardware models']
            #show chasssic hardware models 2nd
            result_write_file=""
            for command in list_command:
                result_write_file+=apply_command(netConf, command, "1.2",hostNamDev)
            netConf.close()
            if result_write_file!="":
                print("Step 1.2: Done: ... Complete")
                print("Step 1.2: Writing file log 1_2.txt: ... writing")
                # with open(os.path.join(log_dir,pre_file_name+"LCA "+slot+".txt"),"w") as outfile:
                with open(os.path.join(log_dir,pre_file_name+"LCA "+lca_sn+".txt"),"w") as outfile:
                    outfile.write(result_write_file)
                print("Step 1.2:Writing log 1_2.txt: ... complete")
                new_status="Checked"
                break
        except MaxRetriesExceeded as err:
            print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
            raise
        except exception.ConnectError as err:
            t+=1
            logging.exception(err)
            print(err)
            time.sleep(3)
            continue
        except Exception as err:
            netConf.close()
            t+=1
            logging.exception(err)
            print(err)
            time.sleep(3)
    update_db(conn_db, hostname, lca_sn,new_status, hd)

def FirstStepChassis(hostname, pre_file_name, IpHost, UserName, PassWord, conn_db, sn, hd, request_reboot, hostNamDev, log_dir):
    list_commands_on_hd={
        '117-2025':{
            'commands': ['show vmhost version', 'show chassis routing-engine', 'show vmhost hardware', 'show chassis hardware models', 'show chassis environment | match Routing Engine', 'show chassis hardware models', 'show chassis fabric summary', 'show chassis environment | match SFB', 'show chassis hardware models', 'show chassis environment psm', 'show chassis hardware models | match Fan', 'show chassis environment | match Fan', 'show chassis craft-interface'],
            'slot': 7,
            'type': 'sfb'
        },
        'default':{
            'commands': ['show vmhost version', 'show chassis routing-engine', 'show vmhost hardware', 'show chassis hardware models', 'show chassis hardware', 'show chassis environment | match Routing Engine', 'show chassis hardware models', 'show chassis fabric summary', 'show chassis environment | match CB', 'show chassis hardware models', 'show chassis environment pem', 'show chassis hardware models | match Fan', 'show chassis environment | match Fan', 'show chassis craft-interface'],
            'slot':2,
            'type': 'cb'
        }
    }
    chassis_detail=next((v for k, v in list_commands_on_hd.items() if k in hd), list_commands_on_hd['default'])
    result_write_file=''
    t=1
    while t<=6:
        try:
            if t>5:
                print("operation X exceed 5 retry, exiting")
                logging.critical("operation X exceed 5 retry, exiting")
                raise MaxRetriesExceeded
            netConf=NetConf(IpHost, UserName, PassWord)
            print("First_step get list SN on host")
            device_hardware = CheckSn(netConf,'chassis')
            netConf.close()
            if device_hardware is not None:
                break
        except MaxRetriesExceeded as err:
            print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
            raise
        except exception.ConnectError as err:
                t+=1
                logging.exception('Error connect to {}, {}'.format(IpHost,err))
                print('Error connect to {}, {}'.format(IpHost,err))
                continue
        except Exception as err:
                netConf.close()
                t+=1
                logging.exception('Error check SN of {}, {}'.format(IpHost,err))
                print('Error check SN of {}, {}'.format(IpHost,err))
    if not sn in device_hardware['sn'].to_list():
        logging.exception(f"Chassis with SN {sn} not exist on host {hostname}")
        print(f"SN {sn} not exist on device. Run phase 2.1 again")
        return
    t=1
    while t<=6:
        try:
            if t>5:
                print("operation X exceed 5 retry, exiting")
                logging.critical("operation X exceed 5 retry, exiting")
                raise MaxRetriesExceeded
            print("CHECK 1: get command output to ATP")
            result_show=''
            netConf = NetConf(IpHost, UserName, PassWord)
            print("Step 1.1: Collect command output: ... Waiting")
            for command in chassis_detail['commands']:
                result_show+=apply_command(netConf, command, "1.1",hostNamDev)
            print("Step 1.1: Done: ... Complete")
            netConf.close()
            if result_show!='':
                result_write_file+=result_show
                break
        except MaxRetriesExceeded as err:
            print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
            raise
        except exception.ConnectError as err:
            t+=1
            logging.exception(err)
            print(err)
            time.sleep(3)
            continue
        except Exception as err:
            netConf.close()
            t+=1
            logging.exception(err)
            print(err)
            time.sleep(3)
    if request_reboot=="NO":
        new_status="Checked without reboot"
        result_write_file+=hostNamDev+"User select no reboot\n"
    elif request_reboot=="YES":
        new_status="Checked with reboot"
        print("CHECK 2: Reboot RE: ... Waiting")
        print(f"Step 2.1: Reboot RE: ... Waiting")
        t=1
        while t<=6:
            try:
                if t>5:
                    print("operation X exceed 5 retry, exiting")
                    logging.critical("operation X exceed 5 retry, exiting")
                    raise MaxRetriesExceeded
                netConf=NetConf(IpHost, UserName, PassWord)
                print("Step 2.1.1: Getting routing engine master slot")
                result_show=""
                master_slot = get_master_RE(netConf)
                result_show+=apply_command(netConf,'show chassis routing-engine',"2.1.1",hostNamDev)
                netConf.close()
                if master_slot.isdigit() and result_show:
                    result_write_file+=result_show
                    break
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                    t+=1
                    print('Error connect to {}, {}'.format(IpHost,err))
                    logging.exception('Error connect to {}, {}'.format(IpHost,err))
                    continue
            except Exception as err:
                    netConf.close()
                    t+=1
                    logging.exception('Error getting routing engine of {}, {}'.format(IpHost,err))
                    print('Error getting routing engine of {}, {}'.format(IpHost,err))
        t=1
        while t<=21:
            try:
                if t>20:
                    print("operation X exceed 21 retry, exiting")
                    logging.critical("operation X exceed 21 retry, exiting")
                    raise MaxRetriesExceeded
                netConf=NetConf(IpHost, UserName, PassWord)
                print(f"Step 2.1.2: Reboot RE {master_slot}: ... Waiting")
                result_show=apply_command(netConf,'request vmhost reboot',"1.3",hostNamDev)
                print(f"Step 2.1.2: Reboot RE {master_slot}: ... Done")
                netConf.close()
                if result_show:
                    result_write_file+=result_show
                    break
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                    t+=1
                    print('Error connect to {}, {}'.format(IpHost,err))
                    logging.exception('Error connect to {}, {}'.format(IpHost,err))
                    continue
            except Exception as err:
                    netConf.close()
                    t+=1
                    print('Error reboot chassis of {}, {}'.format(IpHost,err))
                    logging.exception('Error reboot chassis of {}, {}'.format(IpHost,err))
        t=1
        while t<=21:
            try:
                if t>20:
                    print("operation X exceed 20 retry, exiting")
                    logging.critical("operation X exceed 20 retry, exiting")
                    raise MaxRetriesExceeded
                print("Step 2.1.3: Connecting to device after reboot RE")
                netConf = NetConf(IpHost, UserName, PassWord)
                print("Step 2.1.3: Getting routing engine master slot")
                master_slot_current = get_master_RE(netConf)
                netConf.close()
                if master_slot_current.isdigit() and int(master_slot_current)!=int(master_slot):
                    print(f"Step 2.1: Reboot RE: ... Done")
                    break
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                print("Step 2.1.3: Cannot connect to device after reboot. Retry in 20s")
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(20)
                continue
            except Exception as err:
                netConf.close()
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(20)

        print(f"CHECK 3: Offline/Online SCB/SFB : ... Waiting")
        print(f"Step 3.1: check status {chassis_detail['type']} {chassis_detail['slot']} and online if offline")
        t=1
        while t<=21:
            try:
                if t>20:
                    print("operation X exceed 20 retry, exiting")
                    logging.critical("operation X exceed 20 retry, exiting")
                    raise MaxRetriesExceeded
                netConf = NetConf(IpHost, UserName, PassWord)
                cb_state = get_state_cb_sfb(netConf, type=chassis_detail['type'], slot=chassis_detail['slot'])
                if cb_state == "Offline":
                    print(f"Step 3.1.1: {chassis_detail['type']} {chassis_detail['slot']} status is {cb_state}. ONLINE to start ATP")
                    OnlineCB_SFB(netConf,chassis_detail['type'],chassis_detail['slot'], hostNamDev,"3.1.1")
                    time.sleep(10)
                    netConf.close()
                    continue
                elif cb_state=="Online":
                    print(f"Step 3.1: {chassis_detail['type']} {chassis_detail['slot']} status is {cb_state}")
                    netConf.close()
                    time.sleep(10)
                    break
                else:
                    print(f"Step 3.1.2: Waiting {chassis_detail['type']} {chassis_detail['slot']} online")
                    t+=1
                    netConf.close()
                    print(f"Step 3.1.2: {chassis_detail['type']} {chassis_detail['slot']} status is {cb_state}")
                    print("Step 3.1.2: Waiting 30s...Waiting")
                    time.sleep(30)
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(30) ####default 3s
                continue
            except Exception as err:
                netConf.close()
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(30) ####default 3s
        t=1
        print(f"Step 3.2: Reboot {chassis_detail['type']} {chassis_detail['slot']}")
        while t<=21:
            try:
                if t>20:
                    print("operation X exceed 20 retry, exiting")
                    logging.critical("operation X exceed 20 retry, exiting")
                    raise MaxRetriesExceeded
                print(f"Step 3.2.1: check {chassis_detail['type']} {chassis_detail['slot']} state")
                netConf = NetConf(IpHost, UserName, PassWord)
                cb_state = get_state_cb_sfb(netConf,type=chassis_detail['type'], slot=chassis_detail['slot'])
                if cb_state == "Online":
                    print(f"Step 3.2.1: {chassis_detail['type']} {chassis_detail['slot']} status is "+cb_state)
                    result_show= RebootCB_SFB(netConf,chassis_detail['type'],chassis_detail['slot'],hostNamDev,"1.3")
                    netConf.close()
                    time.sleep(60)
                    continue
                elif cb_state == "Offline":
                    print(f"Step 3.2.1: {chassis_detail['type']} {chassis_detail['slot']} status is "+cb_state)
                    result_write_file+=result_show
                    netConf.close()
                    time.sleep(10)
                    break
                else:
                    t+=1
                    netConf.close()
                    print(f"Step 3.2.1: {chassis_detail['type']} {chassis_detail['slot']} status is "+cb_state)
                    print("Step 3.2.1: Waiting 30s...Waiting")
                    time.sleep(30)
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)
                continue
            except Exception as err:
                netConf.close()
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)
        print(f"Step 3.3: Check {chassis_detail['type']} {chassis_detail['slot']}")
        t=1
        while t<=6:
            try:
                if t>5:
                    print("operation X exceed 5 retry, exiting")
                    logging.critical("operation X exceed 5 retry, exiting")
                    raise MaxRetriesExceeded
                netConf = NetConf(IpHost, UserName, PassWord)
                result_show= apply_command(netConf,f"show chassis environment {chassis_detail['type']} {chassis_detail['slot']}","3.3",hostNamDev)
                netConf.close()
                if result_show:
                    result_write_file+=result_show
                    break
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)
                continue
            except Exception as err:
                netConf.close()
                t+=1
                logging.exception(err)
                print(err)
                time.sleep(3)
        print(f"Step 3.4: Online {chassis_detail['type']} {chassis_detail['slot']}")
        while t<=21:
            try:
                if t>20:
                    print("operation X exceed 20 retry, exiting")
                    logging.critical("operation X exceed 20 retry, exiting")
                    raise MaxRetriesExceeded
                netConf = NetConf(IpHost, UserName, PassWord)
                cb_state = get_state_cb_sfb(netConf, type=chassis_detail['type'], slot=chassis_detail['slot'])
                if cb_state == "Offline":
                    print(f"Step 3.4.1: {chassis_detail['type']} {chassis_detail['slot']} status is "+cb_state)
                    result_show = OnlineCB_SFB(netConf,chassis_detail['type'],chassis_detail['slot'],hostNamDev,"3.4.1")
                    netConf.close()
                    time.sleep(10)
                    continue
                elif cb_state=="Online":
                    print(f"Step 3.4: {chassis_detail['type']} {chassis_detail['slot']} status is "+cb_state)
                    result_write_file+=result_show
                    netConf.close()
                    time.sleep(30)
                    break
                else:
                    t+=1
                    netConf.close()
                    print(f"Step 3.4.1: {chassis_detail['type']} {chassis_detail['slot']} status is "+cb_state)
                    print("Step 3.4.1: Waiting 30s...Waiting")
                    time.sleep(30)
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                t+=1
                print(err)
                logging.exception(err)
                time.sleep(3)
                continue
            except Exception as err:
                netConf.close()
                t+=1
                print(err)
                logging.exception(err)
                time.sleep(3)
        print(f"Step 3.5: Check {chassis_detail['type']} {chassis_detail['slot']}")
        t=1
        while t<=6:
            try:
                if t>5:
                    print("operation X exceed 5 retry, exiting")
                    logging.critical("operation X exceed 5 retry, exiting")
                    raise MaxRetriesExceeded
                netConf = NetConf(IpHost, UserName, PassWord)
                result_show= apply_command(netConf,f"show chassis environment {chassis_detail['type']} {chassis_detail['slot']}","3.5",hostNamDev)
                netConf.close()
                if result_show:
                    result_write_file+=result_show
                    break
            except MaxRetriesExceeded as err:
                print(f"CRITICAL ERROR: Caught MaxRetriesExceeded at t={t}: {err}. Stopping execution.")
                raise
            except exception.ConnectError as err:
                t+=1
                print(err)
                logging.exception(err)
                time.sleep(3)
                continue
            except Exception as err:
                netConf.close()
                t+=1
                print(err)
                logging.exception(err)
                time.sleep(3)
    print("CHECK 4: Writing file log: ... writing")
    with open(os.path.join(log_dir,pre_file_name+"Chassis "+sn+".txt"),"w") as outfile:
        outfile.write(result_write_file)
    print("Step 1.2:Writing log: ... complete")
    update_db(conn_db, hostname, sn,new_status, hd)

def main():
#   ===========INPUT INITIATION
    args = PARSE_ARGS ( )
    UserName=args.username
    Password=args.password
    hd=args.hopdong
    hostname=args.hostname
    hostslot=args.hostslot
    request_reboot=args.request_reboot
    output_dir=args.output_dir

#   =========== LOG INITIATION SEQUENCE
    dt = datetime.now()
    seq = str(dt.strftime("%Y%m%d"))
    pre_file_name ="Phase2.2-"+ hostname+"_"+seq
    log_file_name = ("{}.log".format(pre_file_name))

    from  distutils import util
    LOGGER_INIT( log_level = args.log_level ,
							log_file = log_file_name ,
							shell_output = util.strtobool(args.shell_output) ,
							print_log_init = True)

#   =========== MAIN OPERATION
    database=os.path.join(output_dir,args.database_name)
    conn = sqlite3.connect(database)
    host=pd.read_sql_query("SELECT * FROM 'BBBG' where Hostname=(?) and ma_HD=(?)" , conn, params=(hostname,hd)).iloc[0]
    bbbg=host['tail']
    IpHost=host["IP"]
    pre_file_name=bbbg+'_'+hostname+'_'
    hostslot=hostslot.split(',')
    for item in hostslot:
        hw_type=item.split(' - ')[1].split(' ')[0]
        if hw_type!='chassis':
            slot=re.search("Slot (.*)",item.split(' - ')[2]).group(1)
            print("CHECK REBOOT: "+hd+' - '+IpHost+' - Slot '+slot)
        else:
            sn=re.search("chassis (.*)",item.split(' - ')[1]).group(1)
            print("CHECK REBOOT: "+hd+' - '+IpHost+' - Chassis SN '+sn)
        hostNamDev=UserName+"@"+hostname+"> "
        print("The first step\r\n")
        log_dir=os.path.join(output_dir,hd, "RAW LOG")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        if hw_type=='fpc':
            FirstStepFPC(hostname, pre_file_name,IpHost, UserName, Password, conn, slot, hd, request_reboot,hostNamDev,log_dir)
        elif hw_type=='module':
            FirstStepModule(hostname, pre_file_name,IpHost, UserName, Password, conn, slot, hd,hostNamDev,log_dir)
        elif hw_type=='lca':
            FirstStepLCA(hostname, pre_file_name,IpHost, UserName, Password, conn, slot, hd,hostNamDev,log_dir)
        elif hw_type=='chassis':
            FirstStepChassis(hostname, pre_file_name, IpHost, UserName, Password, conn, sn, hd, request_reboot, hostNamDev,log_dir)
    conn.close()

def PARSE_ARGS():
    """Parse command-line args"""
    parser = argparse.ArgumentParser(description='\nDemo reading argument when running script')
    INIT_LOGGING_ARGS(parser)
#====================================================
    parser.add_argument(
                '-u',
                '--username',
                type=str,
                default="",
                help='\n\t\tLogin username')

    parser.add_argument(
                '-p',
                '--password',
                type=str,
                default="",
                help='\n\t\tLogin password')


    parser.add_argument(
                '-hn',
                '--hostname',
                type=str,
                default = "",
                #required=True,
                help='\n\t\tHostname')
    parser.add_argument(
                '-hs',
                '--hostslot',
                type=str,
                #default = "",
                #required=True,
                help='\n\t\tCombo Hostname-Slot-SN-Status split by ,')
    parser.add_argument(
                '-hd',
                '--hopdong',
                type=str,
                #default = "",
                #required=True,
                help='\n\t\tHop dong')
    parser.add_argument(
                '-o',
                '--output_dir',
                type=str,
                default = "/opt/ATP_output_result",
                #required=True,
                help='\n\t\tOutput directory')
    parser.add_argument(
                '-db',
                '--database_name',
                type=str,
                default="database.sqlite",
                help='\n\t\tDatabase full name')
    parser.add_argument(
                '-reboot',
                '--request_reboot',
                choices = [ 'YES' , 'NO' ] ,
                default="NO",
                help='\n\t\tReboot?')
    parser.add_argument(
                '-shell_output',
                '--shell_output',
                choices = [ 'YES' , 'NO' ] ,
                default="NO",
                help='\n\t\toutput debug log file stdout?')
    return parser.parse_args()

if __name__ == "__main__":
    main()