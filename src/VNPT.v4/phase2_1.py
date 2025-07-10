import os
from glob import glob
import re
from copy import deepcopy
import pandas as pd
import time
import logging
from jnpr.junos import Device, exception
import sqlite3
import argparse
import sys
from datetime import datetime
import numpy as np
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root_dir = os.path.abspath(os.path.join(current_script_dir, '..', '..'))
utils_dir_path = os.path.join(project_root_dir, 'utils')
if utils_dir_path not in sys.path:
    sys.path.insert(0, utils_dir_path)
from module_utils import *

def NetConf(host, username, password):
    print('NetConf')
    NetConfSsh = Device(host=host, user=username, passwd=password, timeout=5, port=22)
    NetConfSsh.open()
    if NetConfSsh.connected == True:
        print("connected to device")
        time.sleep(10)
        return NetConfSsh

def CheckSn(netConf, hostname):
    device_hardware =pd.DataFrame()
    print("checkSN")
    list_data_type=['FPC','PIC','Module','LCA', 'Chassis']
    for data_type in list_data_type:
            tempData = GET_PYEZ_TABLEVIEW_FORMATTED(dev=netConf,tableview_file=os.path.join(current_script_dir, '../hardwareTable.yml'),data_type=data_type,output_format='dataframe')
            if isinstance(tempData, pd.DataFrame) and not tempData.empty:
                tempData['type']=data_type
                if data_type=='LCA':
                    tempData['slot']=tempData['hardware_name'].apply(lambda x: re.search("ADC (\d+)",x).group(1))
                elif data_type=='Module':
                    tempData = tempData.dropna(subset=['hardware_name', 'pic_slot', 'fpc_slot'])
                    tempData['slot']= tempData.apply(lambda x: str(x['fpc_slot'].replace(r'FPC ', ''))+'/'+str(x['pic_slot'].replace(r'PIC ', ''))+'/'+str(x['hardware_name'].replace(r'Xcvr ', '')), axis=1)
                elif data_type=='Chassis':
                    tempData['slot']=None
                else:
                    tempData['slot']=tempData['hardware_name'].apply(lambda x: re.search(data_type+" (\d+)",x).group(1))
                tempData['hostname']=hostname
                device_hardware=pd.concat([device_hardware, tempData[['sn','slot','hostname']]], axis=0)
    return device_hardware

def update_host(hardware_result):
    for index, row in hardware_result.iterrows():
        if pd.isna(row['sn']) or pd.isna(row['slot']):
            continue
        else:
            hardware_result.loc[index,'Hostname']=row['hostname']
            hardware_result.loc[index,'RealSlot']=row['slot']
    return hardware_result

def update_installation_state(hardware_result):
    time_current=time.time()
    for index, row in hardware_result.iterrows():
        if pd.isna(row['sn']) or "Checked" not in row['TestStatus']:
            hardware_result.loc[index,'SN_status_update_timestamp']=time_current
            hardware_result.loc[(hardware_result['SN_status_update_timestamp']>=hardware_result['SN_create_timestamp']), 'StatusTestStatus'] = "Valid"
        if pd.isna(row['sn']):
            hardware_result.loc[index,'TestStatus']='Not-Installed'
            hardware_result.loc[index,'InstallationStatus']=None
        else:
            if "Checked" not in row['TestStatus'] and row['RealSlot']==row['PlannedSlot']:
                hardware_result.loc[index,'TestStatus']='Installed'
                hardware_result.loc[index,'InstallationStatus']="Valid"
            elif "Checked" not in row['TestStatus'] and row['RealSlot']!=row['PlannedSlot']:
                hardware_result.loc[index,'TestStatus']='Installed'
                hardware_result.loc[index,'InstallationStatus']="Invalid"
    return hardware_result

def main():
#   ===========INPUT INITIATION
    args = PARSE_ARGS ( )
    UserName=args.username
    Password=args.password
    hd=args.hopdong
    list_bbbg=args.bbbg.split(',')
    output_dir=args.output_dir
    database=os.path.join(output_dir,args.database_name)
    conn = sqlite3.connect(database)
    cursor = conn.cursor()
    for bbbg in list_bbbg:
        print("----------------------Check serial-number for "+bbbg+'-----------------------')
        #   =========== LOG INITIATION SEQUENCE
        dt = datetime.now()
        seq = str(dt.strftime("%Y%m%d"))
        pre_file_name ="Phase2.1-"+ bbbg.replace(" ", "_" )+"_"+seq
        log_file_name = ("{}.log".format(pre_file_name))
        from  distutils import util
        LOGGER_INIT( log_level = args.log_level ,
                                log_file = log_file_name ,
                                shell_output = util.strtobool(args.shell_output) ,
                                print_log_init = True)

        #   =========== MAIN OPERATION
        hostList=pd.read_sql_query("SELECT Hostname, IP, tail FROM 'BBBG' where tail=(?) and ma_HD=(?)", conn, params=(bbbg,hd))
        checkSNTable=pd.read_sql_query("SELECT * FROM 'checkSN' where BBBG=(?) and ma_HD=(?)" , conn, params=(bbbg,hd))
        hardwareList=pd.DataFrame()
        hostList=hostList.drop_duplicates()
        for index,row in hostList.iterrows():
            t=1
            while t<=6:
                try:
                    if t>5:
                        logging.critical(row['IP']+" operation X exceed 5 retry, exiting")
                        print(row['IP']+" operation X exceed 5 retry, exiting")
                        break
                    print("connect to "+row['IP'])
                    netConf=NetConf(row['IP'], UserName, Password)
                    deviceHardware=CheckSn(netConf, row['Hostname'])
                    netConf.close()
                    hardwareList=pd.concat([hardwareList, deviceHardware], axis=0)
                    if deviceHardware is not None:
                        break
                except exception.ConnectError as err:
                    t+=1
                    print(err)
                    logging.exception(err)
                    continue
                except Exception as err:
                    netConf.close()
                    t+=1
                    print(err)
                    logging.exception(err)
        if not hardwareList.empty:
            print("Compare database and device information")
            hardware_result=pd.merge(checkSNTable, hardwareList[['sn','slot','hostname']],  how='left', left_on=['SN'], right_on = ['sn'])
            hardware_result=update_host(hardware_result)
            hardware_result=update_installation_state(hardware_result)
            hardware_result=hardware_result.drop(columns=['hostname','slot','sn'])
            for index, row in hardware_result.iterrows():
                cursor.execute('UPDATE "checkSN" SET TestStatus=?, InstallationStatus=?, RealSlot=?, Hostname=?, SN_status_update_timestamp=?, StatusTestStatus=? WHERE BBBG=? and SN=? and ma_HD=?', [row['TestStatus'], row['InstallationStatus'], row['RealSlot'],row['Hostname'], row['SN_status_update_timestamp'], row['StatusTestStatus'], row['BBBG'], row['SN'], hd])
            conn.commit()
            print("Updated databse successfully")
        else:
            logging.warning("No compared slot in "+bbbg)
            print("No compared slot in "+bbbg)
    cursor.close()
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
                '-hd',
                '--hopdong',
                type=str,
                #default = "",
                #required=True,
                help='\n\t\tHop dong')
    parser.add_argument(
                '-b',
                '--bbbg',
                type=str,
                default="",
                help='\n\t\tList BBBG string split by ,')
    parser.add_argument(
                '-o',
                '--output_dir',
                type=str,
                default="/opt/ATP_output_result",
                help='\n\t\tOutput directory')
    parser.add_argument(
                '-db',
                '--database_name',
                type=str,
                default="database.sqlite",
                help='\n\t\tDatabase full name')
    parser.add_argument(
                '-shell_output',
                '--shell_output',
                choices = [ 'YES' , 'NO' ] ,
                default="NO",
                help='\n\t\toutput debug log file stdout?')
    return parser.parse_args()

if __name__ == "__main__":
    main()