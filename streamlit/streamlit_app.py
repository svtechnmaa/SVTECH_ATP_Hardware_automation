import streamlit as st
import sys
import os
from functools import partial
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root_dir = os.path.abspath(os.path.join(current_script_dir, '..'))
utils_dir_path = os.path.join(project_root_dir, 'utils')
if utils_dir_path not in sys.path:
    sys.path.insert(0, utils_dir_path)
from streamlit_utils import *

conf=read_conf()
all_phase=conf['input_vars']
pages_list = []
db_path=os.path.join(conf['OUTPUT_DIR'], conf['DB_NAME'])
log_path=os.path.join(conf['OUTPUT_DIR'], conf['DB_LOG'])
if 'running' not in st.session_state:
    st.session_state.running = False
for phase, vars in all_phase.items():
    if f'input_data_phase_{phase}' not in st.session_state:
        st.session_state[f'input_data_phase_{phase}'] = {}
    if phase!='1.1':
        if os.path.exists(db_path):
            st.session_state[f'{phase}_hopdong_options'] = get_list_hd(database=db_path)
        else:
            st.session_state[f'{phase}_hopdong_options'] = []
    if phase in ['2.1','2.2', '2.3']:
        if not st.session_state[f'{phase}_hopdong_options']:
            st.session_state[f'{phase}_list_bbbg_options'] = []
        else:
            if  f"phase_{phase}_hopdong" in st.session_state:
                hd= st.session_state[f"phase_{phase}_hopdong"]
            elif f'hopdong' in st.session_state[f'input_data_phase_{phase}']:
                hd=st.session_state[f'input_data_phase_{phase}']['hopdong']
            else:
                hd=st.session_state[f'{phase}_hopdong_options'][0]
            st.session_state[f'{phase}_list_bbbg_options']=get_list_bbbg(database=db_path, hd=hd)
        if phase=='2.2':
            if not st.session_state[f'{phase}_hopdong_options']:
                st.session_state[f'{phase}_hostname_options'] = []
                st.session_state[f'{phase}_hostslot_options'] = []
            else:
                st.session_state[f'{phase}_hostname_options']=get_list_host(database=db_path, hd=hd)
                if  f"phase_{phase}_hostname" in st.session_state:
                    host= st.session_state[f"phase_{phase}_hostname"]
                elif f'hostname' in st.session_state[f'input_data_phase_{phase}']:
                    host=st.session_state[f'input_data_phase_{phase}']['hostname']
                else:
                    host=st.session_state[f'{phase}_hostname_options'][0]
                st.session_state[f'{phase}_hostslot_options']=get_list_sn(database=db_path, hd=hd, host=host)
    statistics=get_statistics(database=log_path, phase=phase)
    list_runs=get_list_run(database=log_path, phase=phase)
    page_func = partial(render_phase_page, phase=phase, vars=vars, statistics=statistics, list_runs=list_runs)
    product_page = st.Page(
        page_func,
        title=f"{phase}",
        url_path=f"atp_phase_{phase}",
    )
    pages_list.append(product_page)
pages_list.append(st.Page("pages/running.py", title="Run job"))
pages_list.append(st.Page("pages/dashboard.py", title="Summary"))
st.set_page_config(layout="wide")
pg = st.navigation(pages_list)
pg.run()