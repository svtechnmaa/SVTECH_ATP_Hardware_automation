import logging
import os
import sys
import time

OK = 0
WARNING = 1
CRITICAL = 2
UNKNOWN = 3

data_format_dict =     {
                         "list" : {   "format_names":( "list", "python list"),
                                             "convert_func" : "PYEZ_TABLEVIEW_TO_LIST",
                                             "write_func" : "WRITE_PY_STRUCT_TO_FILE"},

                         "dict" : {    "format_names": ( "dict","dictionary"),
                                              "convert_func" : "PYEZ_TABLEVIEW_TO_DICT",
                                              "write_func" : "WRITE_PY_STRUCT_TO_FILE"},

                          "list_of_dict": { "format_names": ( "list_of_dict", "list of dict"),
                                                   "convert_func" : "PYEZ_TABLEVIEW_TO_LIST_OF_DICT",
                                                   "write_func" : "WRITE_PY_STRUCT_TO_FILE"},

                          "json" : { "format_names": ( "json"),
                                            "convert_func" : "PYEZ_TABLEVIEW_TO_JSON",
                                            "write_func" : "WRITE_JSON_TO_FILE",},

                          "xml" : { "format_names": ( "xml"),
                                                    "convert_func" : "PYEZ_TABLEVIEW_TO_XML",
                                                    "write_func" : "WRITE_XML_TO_FILE"},

                          "csv" : { "format_names" : (  "csv",  "xls" , "excel", "dataframe"),
                                                    "convert_func" : "PYEZ_TABLEVIEW_TO_DATAFRAME",
                                                    "write_func" : "WRITE_DATAFRAME_TO_FILE"},
                         #                           "convert_func" : "GET_PYEZ_TABLEVIEW_RAW",
                         #                           "write_func" : "PYEZ_TABLEVIEW_TO_CSV"},

                         "tableview": { "format_names" : (  "tableview", "raw"),
                                                    "convert_func" : "GET_PYEZ_TABLEVIEW_RAW",
                                                    #"write_func" : "WRITE_PYEZ_TABLEVIEW_RAW"}, #TODO
                                                    "write_func" : "WRITE_PY_STRUCT_TO_FILE"},
                        }


try:
    logging.debug("Testing if importing pandas is possible")
    import pandas
except Exception as e:
    logging.warning("Failed to import pandas due to {}, using csv-based functions".format(e))
    data_format_dict["csv"]["convert_func"] = "GET_PYEZ_TABLEVIEW_RAW"
    data_format_dict["csv"]["write_func"] = "PYEZ_TABLEVIEW_TO_CSV"

def get_rpc_hostname(dev=None):
    sw = dev.rpc.get_system_information()
    try:
        hostname = sw.xpath('//system-information/host-name')
        hostname = hostname[0].text
    except Exception as e:
        logging.error("Cannot get hostname from device via RPC get_system_information, due to [ {} ]".format(e))
        hostname = None
    return hostname

def PYEZ_TABLEVIEW_TO_LIST_OF_DICT( dev=None,
                                    tableview_obj=None,
                                    include_hostname=False):
    # type  =   (tableview_obj) -> PyEZTableView
    """Recursively convert Juniper PyEZ Table/View items to list of dicts."""
    try:
        import jnpr.junos.factory.optable as TableModule
        if not isinstance(tableview_obj, TableModule.Table):
            logging.warning("This function need a PyEZ table data, invalid type [ {} ] provided, exiting".format(type(tableview_obj)))
            logging.debug("Received adata is {}".format(tableview_obj))
            return CRITICAL

        listdata = []
        # data.items() is a list of tuples
        data_items = tableview_obj.items()
        if len(data_items) == 0:
            logging.warning("Sub tableview is empty, filling value None to avoid error during subsequent data conversion")
            return 'Nothing'

    except Exception as e:
        logging.error("Failed to initiate list to convert tableview data of [ {} ], due to: [ {} ]".format(tableview_obj.hostname,e))
        return CRITICAL


    for table_key, table_fields in data_items:
        temp = {}
        try:
            for key, value in table_fields:
                if value and isinstance(value, TableModule.Table):
                    if dev != None:
                        value = PYEZ_TABLEVIEW_TO_LIST_OF_DICT(dev=dev, tableview_obj=value, include_hostname=include_hostname) #only allow include_hostname at first call, do not allow during recursion
                    else:
                        value = PYEZ_TABLEVIEW_TO_LIST_OF_DICT(tableview_obj=value, include_hostname=include_hostname) #only allow include_hostname at first call, do not allow during recursion

                # default behavior will be converting tuple to list for json and dataframe handling
                temp[str(key)] = value
                temp['tableview_key'] = str(table_key) #store it inside field dict instead of outside
                # Hostname for json and dataframe later
            if include_hostname == True:
                logging.info ("Converting tableview data of [ {} ] to a list of dict".format(tableview_obj.hostname))
                if dev != None:
                    # temp["hostname"] = format(dev.facts['hostname'])
                    temp["hostname"] = format(get_rpc_hostname(dev))  # tuongvx replace dev.facts with rpc get

                temp["address"] = format(tableview_obj.hostname)
                logging.debug("Appended hostname [ {} ] into converted data ".format(tableview_obj.hostname))

            logging.debug("Converted value [ {} ]".format(temp) )
            listdata.append(temp)
        except Exception as e:
            logging.error("Failed to convert tableview data [ {} ] to list of dict, due to: [ {} ]".format(tableview_obj,e))
            return CRITICAL
    return listdata

def PYEZ_TABLEVIEW_TO_DATAFRAME(dev=None,
                                tableview_obj=None,
                                include_hostname=False):
    # type  =   (tableview_obj) -> PyEZTableView
    # type  =   (output_filename) -> str
    """Recursively convert Juniper PyEZ Table/View items to list of dicts, then to dataframe"""
    from pandas import DataFrame
    if dev != None:
        data_list = PYEZ_TABLEVIEW_TO_LIST_OF_DICT(dev=dev, tableview_obj=tableview_obj,include_hostname=include_hostname)
    else:
        data_list = PYEZ_TABLEVIEW_TO_LIST_OF_DICT(tableview_obj=tableview_obj,include_hostname=include_hostname)

    if data_list == CRITICAL or data_list == WARNING or data_list is None:
        logging.warning("Table data of [ {} ] was not converted to list of dict, dataframe will not be created, exit code for conversion was [ {} ]".format(tableview_obj.hostname,data_list))
        return WARNING

    try:
        logging.info("Converting from PyEZ table [ {} ] > list_of_dict > dataframe".format(tableview_obj))
        dataframe = DataFrame(data_list)
    except Exception as e:
        logging.error("Failed to convert table data [ {} ] to dataframe due to [ {} ]".format(tableview_obj,e))
        return CRITICAL

    return dataframe

class OneLineExceptionFormatter(logging.Formatter):
    def formatException(self, exc_info):
        result = super(OneLineExceptionFormatter, self).formatException(exc_info)
        return repr(result) # or format into one line however you want to

    def format(self, record):
        s = super(OneLineExceptionFormatter, self).format(record)
        if record.exc_text:
            s = s.replace('\n', '') + '|'
        return s

def PRINT_W_TIME ( message = "" ,
                   timestamp = time.strftime ( '%x' ) + "  " + time.strftime ( '%X' ) ) :
    #timestamp = "avoiding error, break-fix"
    for lines in message.splitlines ( ) :
        print ("{}\t{}".format(timestamp,message))

def INIT_LOGGING_ARGS(parser):
    # ===================================================Logging Parameter======================================================
    log_group = parser.add_argument_group( #actually not neccessary, for Gooey GUI only
         "Log Options",
         "Customize the log options"
    )
    log_group.add_argument('--log_size',
                        dest = "log_size",
                        type=int,
                        default=2 * 1024 * 1024,
                        help='        Size for log file ')

    log_group.add_argument('--log_count',
                        dest = "log_count",
                        type=int,
                        default=2,
                        help='        Number of log file ')

    log_group.add_argument('--log_prefix',
                        dest = "log_prefix",
                        type=str,
                        default="",
                        help='        Prefix for log file ')

    log_group.add_argument('--log_surfix',
                        dest = "log_surfix",
                        type=str,
                        default="",
                        help='        Surfix for log file ')

    log_group.add_argument('--log_timestamp',
                        dest = "log_timestamp",
                        type=str,
                        default="%Y-%m-%d",
                        help='         timestamp in strftime format for log file')

    log_group.add_argument('--log_level',
                        dest = "log_level",
                        choices = [ 'DEBUG' , 'INFO' , 'WARNING' , 'ERROR' , 'CRITICAL' ] ,
                        default="WARNING",
                        help='        log level')

    if "win" in sys.platform.lower() and 'gooey' in sys.modules:
        log_group.add_argument('--log_dir',
                            dest = "log_dir",
                            type=str,
                            default=".",
                            widget = "DirChooser", #require Gooey on Windows platform
                            help='        dir to store log file ')
    else:
        log_group.add_argument('--log_dir',
                            dest = "log_dir",
                            type=str,
                            default=".",
                            help='        dir to store log file ')

def CREATE_EXPORT_DIR ( directory = "./" ) :
    # type: (directory) -> string
    """CREATE DIR"""
    if not os.path.exists ( directory ) :
        os.makedirs ( directory )
        logging.debug ( 'Created new directory: ' + directory )
    else :
        logging.debug ( 'Directory already existed ' + directory )
    return directory

def LOGGER_INIT ( log_level = logging.INFO ,
                  log_file = 'unconfigured_log.log' ,
                  file_size = 2 * 1024 * 1024 ,
                  file_count = 2 ,
                  shell_output = False ,
                  log_file_mode = 'a' ,
                  log_format = '%(asctime)s %(levelname)s %(funcName)s(%(lineno)d)     %(message)s',
                  print_log_init = False) :
    try :
        main_logger = logging.getLogger ( )
        main_logger.setLevel ( log_level )
        # add a format handler
        log_formatter = OneLineExceptionFormatter ( log_format )

    except Exception as e :
        PRINT_W_TIME ( "Exception  when format logger cause by:    {}".format( e ) )
        logging.error ( "Exception  when format logger cause by:    {}".format( e ) )

    log_dir = os.path.dirname( os.path.abspath(log_file) )
    if print_log_init == True: PRINT_W_TIME("Creating log directory ()".format(log_dir))


    try :
        main_logger.handlers = [] #init blank handler first otherwise the stupid thing will create a few and print to console
        main_logger.propagate = False #Only need this if basicConfig is used

        # add a rotating handler
        from logging.handlers import RotatingFileHandler
        log_rorate_handler = RotatingFileHandler ( log_file ,
                                                   mode = log_file_mode ,
                                                   maxBytes = file_size ,
                                                   backupCount = file_count ,
                                                   encoding = None ,
                                                   delay = 0 )
        log_rorate_handler.setFormatter ( log_formatter )
        log_rorate_handler.setLevel ( log_level )
        #add the rotation handler only
        main_logger.addHandler ( log_rorate_handler )

    except Exception as e :
        PRINT_W_TIME ( "Exception when creating main logger handler cause by:    {}".format( e ) )
        logging.error ( "Exception when creating main logger handler cause by:    {}".format( e ) )

    try :
        CREATE_EXPORT_DIR ( log_dir ) # Only do this after the 2 above step, otherwise fcking main_logger will spam debug log to stdout
        if shell_output == True :
            stream_log_handler = logging.StreamHandler ( stream = sys.stdout )
        else:
            #by default StreamHandler already set stream = stderr, but somehome if leave alone it will cause streamlit error
            stream_log_handler = logging.StreamHandler ( )

        stream_log_handler.setFormatter ( log_formatter )
        stream_log_handler.setLevel ( log_level )
        #add the stdout handler properly
        main_logger.addHandler ( stream_log_handler )

    except Exception as e :
        PRINT_W_TIME ( "Exception when creating log directory and setup log stdout handler cause by:    {}".format( e ) )
        logging.error ( "Exception when creating log directory and setup log stdout handler cause by:    {}".format ( e ) )

    if print_log_init == True: PRINT_W_TIME("Done, logging level {} to {} ".format(log_level , os.path.abspath(log_file)) )

def FORMAT_PYEZ_TABLEVIEW(dev=None,
                          tableview_obj=None,
                          include_hostname=False,
                          output_format = 'dictionary'):
    #""" get hardware information of junos device into a list of tableview item"""
    #type  =   tableview_obj -> jnpr.junos.factory.optable.TableModule.Table
    #type  =   output_format -> string
    import jnpr.junos.factory.optable as TableModule
    if not isinstance(tableview_obj, TableModule.Table):
        logging.warning("This function need a PyEZ table data, invalid type [ {} ] provided, exiting".format(type(tableview_obj)))
        logging.debug("Received adata is {}".format(tableview_obj))
        return CRITICAL

    global data_format_dict

    data_type_exist = False
    for data_format_names,data_format_metadata in data_format_dict.items(): #use iteritems in python 2
        #traversing the dictionary of possible output format, put the raw table through the corresponding convert function
        if output_format.lower() in data_format_metadata["format_names"]:
            data_type_exist = True
            convert_func_name = data_format_metadata['convert_func']

            if convert_func_name == "GET_PYEZ_TABLEVIEW_RAW":
                result = tableview_obj #If the desired output format is raw, return without any conversion (exception case)
            else:
                logging.debug("convert function name is [ {} ] ".format(convert_func_name))
                #If the desired output format not raw, return by calling the conversion function from global name space. DO NOT use "convert_func_name()" since that require function object, we only a string of the name
                if dev != None:
                    result = globals()[convert_func_name](dev=dev,tableview_obj=tableview_obj,include_hostname=include_hostname)
                else:
                    result = globals()[convert_func_name](tableview_obj=tableview_obj,include_hostname=include_hostname)

                #Another way to call this function
                #from  sys import modules
                #current_module = modules[__name__] #get current module name, because getattr require module name
                #convert_func = getattr(current_module,current_module)
                #result = convert_func(tableview_obj)

    # this compar  ison throw an exception through panda - confusing as fuck, use a check token instead
    #if result == None:
    if not data_type_exist:
         logging.warning("Invalid output format specified [ {} ] ".format(output_format))
         return CRITICAL
    else:
         return result

def valid_yaml(dir, type_page='default'):
    import yaml
    from yamllint import linter # Lib for check yaml grammar
    from yamllint.config import YamlLintConfig # Lib for check yaml grammar
    #Look for list of file yml of directory
    ListFileYml= []
    try:
        for files in os.walk(dir):
            file_list = files[2] #Get file_list
            if len(file_list)==0:
                logging.info("No any file in directory [%s]"%dir)
                return WARNING
            else:
                for i in range(len(file_list)):
                    path = dir + "/" + file_list[i]
                    try:
                        with open(path, "r") as file:
                            content = file.read()
                            conf_ymllint = YamlLintConfig('extends: %s'%type_page)
                            error_content = linter.run(content, conf_ymllint)
                            list_err_content = list(error_content)
                            if len(list_err_content) == 0:
                                ListFileYml.append(file_list[i])
                            else:
                                for i in range(len(list_err_content)):
                                    str1= str(list_err_content[i]).split(':')
                                    print(":red[Check line %s from character %s with *%s*]" %(str1[0], str1[1], str1[2]))
                    except Exception as e:
                        print("Error loading file:", e)
                        continue
        return ListFileYml
    except Exception as e:
        logging.error("Failed to lookup file in directory [%s], error code [%s]"%(dir, e))
        return CRITICAL

def GET_TABLEVIEW_CATALOGUE(dir_tableview= '/opt/SVTECH-Junos-Automation/Junos_tableview'):
    import re
    import yaml
    if dir_tableview == '':
        logging.info("Need info of directory.")
        return WARNING
    else:
        #Look for list of dict Tableview
        list_dict_tv= {}
        ListFileYml = valid_yaml(dir_tableview, "table")
    if len(ListFileYml) != 0:
        try:
            for j in range(len(ListFileYml)):
                path = dir_tableview + "/" + ListFileYml[j]
                file_yml = yaml.load(open(path,"r"), Loader=yaml.FullLoader)
                res_table = {key: val for key, val in file_yml.items() if key.endswith("Table")}  # Get dict Table
                res_view = {key: val for key, val in file_yml.items() if key.endswith("iew")}  # Get dict View
                if res_table:
                    # Save table to dict
                    for i in range(len(list(res_table.keys()))):
                        list_dict_tv[list(res_table.keys())[i]]= {
                                'content': res_table.get(list(res_table.keys())[i]),
                                'view': res_table.get(list(res_table.keys())[i]).get('view'),
                                'dir': path
                        }
                else:
                    logging.error("Don't have any table in file [%s]"%path)
                    return WARNING
                if res_view:
                    # Save view to dict
                    for i in range(len(list(res_view.keys()))):
                        list_dict_tv[list(res_view.keys())[i]]= {
                                'content': res_view.get(list(res_view.keys())[i]),
                                'dir': path
                        }
                else:
                    logging.error("Don't have any view in file [%s]"%path)
                    return WARNING
            return list_dict_tv
        except Exception as e:
            logging.error("An exception occurred, check error %s" %e)
            return CRITICAL
    else:
        logging.error("List file yaml empty")
        return CRITICAL

def IMPORT_JUNOS_TABLE_VIEW(TableviewFile):

    if TableviewFile is None:
        logging.warning("Received custom table filename is None, nothing will be imported")
        return WARNING
    elif os.path.isfile(TableviewFile):
        from jnpr.junos.factory.factory_loader import FactoryLoader
        import yaml
        try:
            logging.info("Importing JunosPyEZ custom tableview file [ {} ]".format(TableviewFile))
            with open(TableviewFile, 'r') as TableView:
                tableview_namespace = FactoryLoader().load(yaml.safe_load(TableView))
            return tableview_namespace
        except Exception as e:
            logging.error ( "Error during custom tableview import due to  [ {} ]".format(e))
            logging.exception("Full traceback is here")
            return CRITICAL
    else:
        logging.warning("Table view file {} not found, table will not be imported !!".format(TableviewFile))
        return CRITICAL

def GET_PYEZ_TABLEVIEW_RAW(dev=None,
                           data_type=None,
                           tableview_file=None,
                           kwargs=None):
    #""" get information of junos device into a list of tableview item"""
    #type  =   dev -> junos.jnpr Device
    #type  =   data_type -> string
    #type  =   tableview_file -> string
    #type  =   kwargs -> dict


    TableviewList = IMPORT_JUNOS_TABLE_VIEW(tableview_file)
    if TableviewList == CRITICAL or TableviewList == WARNING:
        logging.error ( "Error during custom tableview import, data will not be fetched")
        return CRITICAL

    else:
        try:
            #if tablename is None and data_type is not None:
            #    tablename = data_type + "Table"
            #    logging.debug("Table name was not provided, using constructed table name " + str(tablename))
            #else:
            #    logging.warning("data type or table name was not provided, no information will be fetched!!")
            #    return WARNING

            tablename =   "{}Table".format(data_type)
            #if TableviewList.has_key(tablename): #only available in python 2
            if tablename in TableviewList:
                logging.info("Found table named [ {} ] in the provided tableview file, getting data".format(tablename))

                #Tu.doan 20/06/2019: Do not open/close socket for each rpc call to avoid connection-limit configuration on device (in case  data collection action require multiple rpc call, for example PortModuleDetail), the main file must handle the opening/closure of socket
                #dev.open(auto_probe=5) # this is required otherwise the bloody thing will wait forever

                logging.debug("Opened netconfig session to {}".format(dev))
                if kwargs is None:
                    #tu.doan 7/05/2019: GET_RPC will return exception if "commands" is used in table definition, rewrite this later
                    #logging.info("No argument provided for the RPC  [ {} ] - getting all data".format(TableviewList[tablename].GET_RPC))
                    logging.info("No argument provided - getting all data")
                    result = TableviewList[tablename](dev).get()
                    # result.address = result.hostname
                    # result.name = dev.facts['hostname']

                else:
                    #tu.doan 7/05/2019: GET_RPC will return exception if "commands" is used in table definition, rewrite this later
                    #logging.info("Some arguments was provided for the RPC  [ {} ], list of args is [ {} ] ".format(TableviewList[tablename].GET_RPC,kwargs))
                    logging.info("Some arguments was provided {}, passing to rpc".format(kwargs))
                    result = TableviewList[tablename](dev).get(**kwargs)
                #dev.close()
            else:
                logging.warning( "Invalid data type or tablename specified, provided file is [ {} ], data_type is [ {} ] and table name is [ {} ]".format(tableview_file,data_type,tablename) )
                return CRITICAL
        except Exception as e:
            logging.error ( "Data fetch from PyEZ tableview failed due to [ {} ]".format(e))
            return CRITICAL

    return result

def GET_PYEZ_TABLEVIEW(dev=None,
                       data_type=None,
                       dir_tableview= '/opt/SVTECH-Junos-Automation/Junos_tableview',
                       kwargs=None):
    #""" get information of junos device into a list of tableview item"""
    #type  =   dev -> junos.jnpr Device
    #type  =   data_type -> string
    #type  =   dir_tableview -> string
    #type  =   kwargs -> dict
    table_name= data_type + 'Table'
    try:
        table_file =  GET_TABLEVIEW_CATALOGUE(dir_tableview= dir_tableview).get(table_name).get('dir')
    except Exception as e:
        logging.error("Can't get table_file [%s] by GET_TABLEVIEW_CATALOGUE" %e)
        return CRITICAL
    logging.error("Da chay vao ham moi roi")
    result = GET_PYEZ_TABLEVIEW_RAW(dev= dev, data_type= data_type, tableview_file= table_file, kwargs= kwargs)
    if result == CRITICAL or result == WARNING:
        logging.error ( "Error during custom tableview import, return value of GET_PYEZ_TABLEVIEW_RAW")
        return CRITICAL
    logging.info('%s'%(dir_tableview + '/' + table_file))
    return result

def GET_PYEZ_TABLEVIEW_FORMATTED(dev=None,
                                 data_type=None,
                                 tableview_file=None,
                                 rpc_kwargs=None,
                                 include_hostname=False,
                                 output_format = 'dictionary'):
    #""" get hardware information of junos device into a list of tableview item"""
    #type  =   dev -> junos.jnpr Device
    #type  =   data_type -> string
    #type  =   tableview_file -> string
    #type  =   output_format -> string
    #type  =   output_type -> string

    tableview_obj_raw = GET_PYEZ_TABLEVIEW_RAW(dev,data_type, tableview_file,rpc_kwargs)

    if tableview_obj_raw in [CRITICAL, WARNING]:
        logging.error("Tableview data will not be converted due to fetch failure for host[ {} ] . return code [ {} ]".format(dev, tableview_obj_raw) )
        return tableview_obj_raw
    else:
        logging.info ("Tableview data fetch complete for [ {} ], formatting data to [ {} ]".format(tableview_obj_raw.hostname,output_format))
        if dev != None:
            result = FORMAT_PYEZ_TABLEVIEW( dev=dev,
                                            tableview_obj=tableview_obj_raw,
                                            include_hostname=include_hostname,
                                            output_format=output_format)

        else:
            result = FORMAT_PYEZ_TABLEVIEW( tableview_obj=tableview_obj_raw,
                                            include_hostname=include_hostname,
                                            output_format=output_format)
        return result