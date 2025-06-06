import argparse
import os
import sqlite3
import pandas as pd
import sys
import logging
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root_dir = os.path.abspath(os.path.join(current_script_dir, '..', '..'))
utils_dir_path = os.path.join(project_root_dir, 'utils')
if utils_dir_path not in sys.path:
    sys.path.insert(0, utils_dir_path)
from module_utils import *

def PARSE_ARGS():
    """Parse command-line args"""
    parser = argparse.ArgumentParser(description='\nDemo reading argument when running script')
    INIT_LOGGING_ARGS(parser)
#====================================================

    parser.add_argument(
                '-p',
                '--planningSN',
                type=str,
                default="/home/hiennn/Documents/ATP_HARDWARE_TOOL1/BASE DIR/planning_400.xlsx",
                help='\n\t\tPlanning SN')
    parser.add_argument(
                '-ps',
                '--planningSN_sheet',
                type=str,
                default="Sheet1",
                help='\n\t\tPlanning SN Sheet')
    parser.add_argument(
                '-hd',
                '--hopdong',
                type=str,
                default="HĐ 400",
                help='\n\t\tHop dong for planning SN')

    parser.add_argument(
                '-o',
                '--output_dir',
                type=str,
                default="/home/hiennn/Documents/ATP_HARDWARE_TOOL1/output",
                help='\n\t\tDirectory save file json')
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
def process_slot_planning(planningSN, output_dir, db_name, hd, planningSN_sheet='Sheet1'):
    database=os.path.join(output_dir,db_name)
    if os.path.exists(planningSN):
        print("Save planning file to database")
        try:
            conn = sqlite3.connect(database)
            cur = conn.cursor()
            df_planning=pd.read_excel(open(planningSN, 'rb'), sheet_name=planningSN_sheet,usecols=['Hostname','Slot','SN'])
            df_planning['ma_HD']=hd
            listOfTables = cur.execute(''' SELECT count(name) FROM sqlite_master WHERE type='table' AND name='slot_planning' ''')
            if listOfTables.fetchone()[0]==0 :
                df_planning.to_sql("slot_planning", con=conn, schema=None, if_exists='replace', index=False, index_label=None, chunksize=None, dtype=None, method=None)
            else:
                planning_db=pd.read_sql_query("SELECT * FROM 'slot_planning'" , conn)
                planning_db = planning_db[planning_db['ma_HD'] !=hd]
                planning_db = pd.concat([planning_db, df_planning])
                planning_db.to_sql("slot_planning", con=conn, schema=None, if_exists='replace', index=False, index_label=None, chunksize=None, dtype=None, method=None)
            planningSN=pd.read_sql_query("SELECT * FROM 'slot_planning'" , conn)
            checkSN=pd.read_sql_query("SELECT * FROM 'checkSN'" , conn)
            checkSN=pd.merge(checkSN, planningSN,  how='left', left_on=['SN','ma_HD'], right_on = ['SN','ma_HD'])
            checkSN["Hostname"] = checkSN["Hostname_y"].fillna(checkSN["Hostname_x"])
            checkSN["PlannedSlot"] = checkSN["Slot"].fillna(checkSN["PlannedSlot"])
            checkSN["RealSlot"] = pd.to_numeric(checkSN["RealSlot"])
            checkSN=checkSN.drop(columns=['Hostname_x', 'Hostname_y',"Slot"])
            checkSN.to_sql("checkSN", con=conn, schema=None, if_exists='replace', index=False, index_label=None, chunksize=None, dtype=None, method=None)
            cur.close()
            print("Updated slot_planning and checkSN table!")
        except Exception as exp:
            logging.exception(exp)
            print(exp)
            raise Exception
    else:
        print("No planning file")
def read_planning():
    args = PARSE_ARGS ( )
    #   =========== LOG INITIATION SEQUENCE
    pre_file_name ="Phase1.2-"+args.hopdong
    log_file_name = ("{}.log".format(pre_file_name))

    from  distutils import util
    LOGGER_INIT( log_level = args.log_level ,
							log_file = log_file_name ,
							shell_output = util.strtobool(args.shell_output) ,
							print_log_init = True)

#   =========== MAIN OPERATION
    process_slot_planning(args.planningSN, args.output_dir, args.database_name, args.hopdong, args.planningSN_sheet)

if __name__ == '__main__':
    read_planning()