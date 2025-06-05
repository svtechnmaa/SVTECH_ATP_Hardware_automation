import os
import re
import pandas as pd
import time
from datetime import datetime
from docx.shared import Pt
import logging
from jnpr.junos import Device, exception
import sys
import sqlite3
import argparse
from glob import glob
import copy
import docx
import pathlib
from docx.table import _Cell


#tu.doan: set the WORKING DIRECTORY to the directory that contain this script, so that relative path to module_utils and tableview file always work, regardless of whether we call python from rundeck or virtualenv or anywhere else
abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
os.chdir(dname)
# sys.path.append('../../../')
# sys.path.append('../../../module_utils')
from module_utils import *

def delete_paragraph(paragraph):
    p = paragraph._element
    p.getparent().remove(p)
    p._p = p._element = None

def move_table_after(table, paragraph):
    tbl, p = table._tbl, paragraph._p
    p.addnext(tbl)

def set_cell_border(cell: _Cell, **kwargs):
    """
    Set cell`s border
    Usage:
    set_cell_border(
        cell,
        top={"sz": 12, "val": "single", "color": "#FF0000", "space": "0"},
        bottom={"sz": 12, "color": "#00FF00", "val": "single"},
        start={"sz": 24, "val": "dashed", "shadow": "true"},
        end={"sz": 12, "val": "dashed"},
    )
    """

    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()

    # check for tag existnace, if none found, then create one
    tcBorders = tcPr.first_child_found_in("w:tcBorders")
    if tcBorders is None:
        tcBorders = OxmlElement('w:tcBorders')
        tcPr.append(tcBorders)

    # list over all available tags
    for edge in ('start', 'top', 'end', 'bottom', 'insideH', 'insideV'):
        edge_data = kwargs.get(edge)
        if edge_data:
            tag = 'w:{}'.format(edge)

            # check for tag existnace, if none found, then create one
            element = tcBorders.find(qn(tag))
            if element is None:
                element = OxmlElement(tag)
                tcBorders.append(element)

            # looks like order of attributes is important
            for key in ["sz", "val", "color", "space", "shadow"]:
                if key in edge_data:
                    element.set(qn('w:{}'.format(key)), str(edge_data[key]))

def write_atp(atp_template, list_log_file, atp_file_path, hd):
    atp_file=copy.deepcopy(docx.Document(atp_template))
    try:
        tables=atp_file.tables
        for table in tables:
            if '510-2024' in hd and "Output-1-" in table.cell(0,0).paragraphs[0].text:
                host=re.search("Output-1-(.*)",table.cell(0,0).paragraphs[0].text).group(1)
                matching = [f for f in list_log_file if f'{host}_Chassis' in f]
                if not matching:
                    continue
                table.cell(0,0).paragraphs[0].text=""
                output={}
                line_index=[]
                lines=[]
                with open(matching[0]) as f:
                    lines = [line.rstrip() for line in f]
                for i in range(len(lines)):
                    if f'@{host}>' in lines[i]:
                        line_index.append(i)
                output={'Output-1':lines[:line_index[6]], 'Output-2':lines[line_index[6]:line_index[9]], 'Output-3':lines[line_index[9]:line_index[11]], 'Output-4':lines[line_index[11]:line_index[13]], 'Output-5':lines[line_index[13]:line_index[14]], 'Output-7':lines[line_index[14]:]}
                for line in output['Output-1']:
                    run = table.cell(0,0).add_paragraph().add_run(line.strip("\n"))
                    run.font.size  = Pt(9)
                    run.font.name = 'Courier New'
                    if "@" in line and '>' in line:
                        run.font.bold = True
                for table2 in tables:
                    if re.search(rf"Output-(2|3|4|5|7)-{host}", table2.cell(0,0).paragraphs[0].text):
                        data=output[f'Output-{re.search(rf"Output-(2|3|4|5|7)-{host}", table2.cell(0,0).paragraphs[0].text).group(1)}']
                        table2.cell(0,0).paragraphs[0].text=""
                        for line in data:
                            run = table2.cell(0,0).add_paragraph().add_run(line.strip("\n"))
                            run.font.size  = Pt(9)
                            run.font.name = 'Courier New'
                            if "@" in line and '>' in line:
                                run.font.bold = True
            elif ('510-2024' in hd and "Output-6-" in table.cell(0,0).paragraphs[0].text) or ('510-2024' not in hd and "Output-1-" in table.cell(0,0).paragraphs[0].text):
                host=re.search("Output-(1|6)-(.*)",table.cell(0,0).paragraphs[0].text).group(2)
                matching = [f for f in list_log_file if re.search(rf'{re.escape(host)}_(FPC|Module|LCA)', f)]
                if not matching:
                    continue
                matching.sort()
                table.cell(0,0).paragraphs[0].text=""
                output_1=[]
                dict_output_2=dict()
                output_2=''
                dict_output_lca=dict()
                dict_output_module=dict()
                str_output_module=''
                for log in matching:
                    file_log=open(log,'r')
                    line_index=[]
                    lines=[]
                    for i, line in enumerate(file_log.readlines()):
                        if f'@{host}>' in line:
                            line_index.append(i+1)
                        lines.append(line)
                    file_log.close()
                    fname = pathlib.Path(log)
                    if 'FPC' in log:
                        output_1+=lines[:(line_index[-2]-1)]
                        dict_output_2[fname.stat().st_mtime]=lines[(line_index[-2]-1):]
                        dict_output_2=dict(sorted(dict_output_2.items()))
                        output_2=dict_output_2[list(dict_output_2.keys())[-1]]
                    elif 'Module' in log:
                        # If only have module in host, get only 1 command show chassis hardware
                        if not any('FPC' in t for t in matching):
                            if '510-2024' in hd:
                                dict_output_module[fname.stat().st_mtime]=lines[(line_index[0]-1):(line_index[2]-1)]
                            else:
                                dict_output_module[fname.stat().st_mtime]=lines[(line_index[0]-1):(line_index[1]-1)]
                            dict_output_module=dict(sorted(dict_output_module.items()))
                            str_output_module=dict_output_module[list(dict_output_module.keys())[-1]]
                        if '510-2024' in hd:
                            output_1+=lines[(line_index[2]-1):]
                        else:
                            output_1+=lines[(line_index[1]-1):]
                    if all("LCA" in s for s in matching):
                        dict_output_lca[fname.stat().st_mtime]=lines
                        dict_output_lca=dict(sorted(dict_output_lca.items()))
                        output_1=dict_output_lca[list(dict_output_lca.keys())[-1]]
                # If only have module in host, parse only 1 command show chassis hardware
                if len(matching)>0 and all('Module' in t for t in matching):
                    output_1=str_output_module+output_1
                #Parsing log linecard, module and lca
                for line in output_1:
                    if "@" in line and '>' in line:
                        run = table.cell(0,0).add_paragraph().add_run(line.strip("\n"))
                        run.font.size  = Pt(9)
                        run.font.name = 'Courier New'
                        run.font.bold = True
                    else:
                        run = table.cell(0,0).add_paragraph().add_run(line.strip("\n"))
                        run.font.size  = Pt(9)
                        run.font.name = 'Courier New'
                for table2 in tables:
                    if ('510-2024' not in hd and "Output-2-"+host in table2.cell(0,0).paragraphs[0].text) or ('510-2024' in hd and "Output-8-"+host in table2.cell(0,0).paragraphs[0].text):
                        #Delete table license result if only module in host
                        if len(matching)>0 and all('Module' in t for t in matching):
                            table2._element.getparent().remove(table2._element)
                            all_paragraph = atp_file.paragraphs
                            tmp=1
                            for item in all_paragraph:
                                if item.text==host:
                                    if ('510-2024' not in hd and tmp==2) or ('510-2024' in hd and (tmp==8 if any("Chassis" in item for item  in list_log_file) else tmp==2)):
                                        delete_paragraph(item)
                                    else:
                                        tmp+=1
                        #Parsing log license
                        elif output_2!='':
                            table2.cell(0,0).paragraphs[0].text=""
                            for line in output_2:
                                if "@" in line and '>' in line:
                                    run = table2.cell(0,0).add_paragraph().add_run(line.strip("\n"))
                                    run.font.size  = Pt(9)
                                    run.font.name = 'Courier New'
                                    run.font.bold = True
                                else:
                                    run = table2.cell(0,0).add_paragraph().add_run(line.strip("\n"))
                                    run.font.size  = Pt(9)
                                    run.font.name = 'Courier New'
        if all('Module' in t for t in list_log_file):
            tmp=1
            for item in atp_file.paragraphs:
                if 'Kết quả test' in item.text:
                    if ('510-2024' not in hd and tmp==2) or ('510-2024' in hd and tmp==8):
                        #Create empty table license result if bbbg only has module
                        new_table=atp_file.add_table(rows=1, cols=1)
                        cell_border_style =  {
                        "top": {"sz": 8, "val": "single"},
                        "bottom": {"sz": 8, "val": "single"},
                        "start": {"sz": 8, "val": "single"},
                        "end": {"sz": 8, "val": "single"},
                        }
                        set_cell_border( cell = new_table.rows[0].cells[0] ,
                        **cell_border_style)
                        #set_cell_background(new_table.rows[0].cells[0], '#d5e0f2')
                        heading_row = new_table.rows[0].cells
                        move_table_after(new_table, item)
                    else:
                        tmp+=1
            for table in tables:
                if len(table.rows) > 1 and re.match(r'Kiểm tra license của linecard(.*)bằng câu lệnh sau',table.cell(1,1).text):
                    #Change text Ket qua in table step license
                    table.cell(1,3).text='Không thực hiện mục này do phân bổ thành phần phần cứng tại trạm không có'
                    table.cell(1,3).paragraphs[0].runs[0].font.size= Pt(12)
                    table.cell(1,3).paragraphs[0].runs[0].font.name = 'Times New Roman'
                    table.cell(1,3).paragraphs[0].alignment = 1 # for left, 1 for center, 2 right, 3 justify ....
                if 'License name' in table.cell(0,0).text:
                    table._element.getparent().remove(table._element)
        atp_file.save(atp_file_path)
    except Exception as exp:
        logging.exception(exp)
        print(exp)

def export_atp(bbbg, hd, output_dir):
    template_dir=os.path.join(output_dir, hd, "ATP Template")
    log_dir=os.path.join(output_dir, hd, "RAW LOG")
    atp_dir=os.path.join(output_dir,hd, "ATP")
    if not os.path.exists(atp_dir):
        os.makedirs(atp_dir)
    print("Writing file ATP docx for "+bbbg+" in hd "+hd)
    list_log_file=glob(os.path.join(log_dir,bbbg+'*.txt'))
    if len(list_log_file)==0:
        print("No log file in bbbg {}".format(bbbg))
        sys.exit()
    atp_file=glob(os.path.join(template_dir,'*'+bbbg+'*.docx'))[0]
    file_name=os.path.join(atp_dir,atp_file.split("/")[-1])
    write_atp(atp_file, list_log_file, file_name, hd)
    print("Writing file ATP docx for "+bbbg+": Done")

def main():
#   ===========INPUT INITIATION
    args = PARSE_ARGS ( )
    hd=args.hopdong
    bbbg=args.bbbg
    output_dir=args.output_dir
    for bbbg in bbbg.split(','):
    #   =========== LOG INITIATION SEQUENCE
        dt = datetime.now()
        seq = str(dt.strftime("%Y%m%d"))
        pre_file_name ="Phase2.3-"+ bbbg.replace(" ", "_" )+"_"+seq
        log_file_name = ("{}.log".format(pre_file_name))

        from  distutils import util
        LOGGER_INIT( log_level = args.log_level ,
                                log_file = log_file_name ,
                                shell_output = util.strtobool(args.shell_output) ,
                                print_log_init = True)
        export_atp(bbbg,hd,output_dir)

def PARSE_ARGS():
    """Parse command-line args"""
    parser = argparse.ArgumentParser(description='\nDemo reading argument when running script')
    INIT_LOGGING_ARGS(parser)
#====================================================
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
                '-b',
                '--bbbg',
                type=str,
                default="NO",
                help='\n\t\BBBG?')
    parser.add_argument(
                '-shell_output',
                '--shell_output',
                choices = [ 'YES' , 'NO' ] ,
                default="NO",
                help='\n\t\toutput debug log file stdout?')
    return parser.parse_args()

if __name__ == "__main__":
    main()