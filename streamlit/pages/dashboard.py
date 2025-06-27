import streamlit as st
import os
import sys
from pathlib import Path
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root_dir = os.path.abspath(os.path.join(current_script_dir, '..'))
utils_dir_path = os.path.join(project_root_dir, 'utils')
if utils_dir_path not in sys.path:
    sys.path.insert(0, utils_dir_path)
from streamlit_utils import *

st.header('ATP Summary')
conf=read_conf()
db_path=os.path.join(conf['OUTPUT_DIR'], conf['DB_NAME'])
status_col_order = ['download','SN', 'Type', 'TestStatus', 'Hostname', 'BBBG', 'ma_HD', 'SN_status_update_timestamp']
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    st.subheader('Serial Number ATP Status Dashboard')
    col1, col2, col3, col0 = st.columns([2.5,3,1.5,3])
    with col1:
        selected_hopdong = st.selectbox("Hopdong", get_list_hd(database=db_path), label_visibility="visible", key='hopdong_status')
    with col2:
        bbbg_options = get_list_bbbg(database=db_path, hd=selected_hopdong)
        all_bbbg_options = ["All"] + bbbg_options
        selected_bbbg = st.multiselect("BBBG", all_bbbg_options, label_visibility="visible", default=['All'], key='bbbg_status')
    with col3:
        status_options=['Unchecked', 'Not-Installed', 'Installed', 'Checked', 'Checked with reboot', 'Checked without reboot']
        all_status_options = ["All"] + status_options
        selected_status = st.multiselect("Status",all_status_options, label_visibility="visible", default=['All'], key='state_status')
    atp_card_zip_buffer=''
    if selected_bbbg and selected_status:
        query_parts = ["SELECT DISTINCT checkSN.Hostname, checkSN.SN, checkSN.Type, checkSN.RealSlot, checkSN.TestStatus, checkSN.BBBG, checkSN.StatusTestStatus, datetime(checkSN.SN_create_timestamp, 'unixepoch', 'localtime') AS SN_create_timestamp, datetime(checkSN.SN_status_update_timestamp, 'unixepoch', 'localtime') AS SN_status_update_timestamp, checkSN.ma_HD FROM checkSN LEFT JOIN BBBG ON checkSN.BBBG = BBBG.tail AND checkSN.ma_HD = BBBG.ma_HD WHERE checkSN.ma_HD = ?"]
        params = [selected_hopdong]
        if "All" not in selected_bbbg and selected_bbbg:
            bbbg_placeholders = ','.join(['?'] * len(selected_bbbg))
            query_parts.append(f"checkSN.BBBG IN ({bbbg_placeholders})")
            params.extend(selected_bbbg)

        if "All" not in selected_status and selected_status:
            status_placeholders = ','.join(['?'] * len(selected_status))
            query_parts.append(f"checkSN.TestStatus IN ({status_placeholders})")
            params.extend(selected_status)
        query = " AND ".join(query_parts)
        cursor.execute(query, params)
        results = cursor.fetchall()
        df=pd.DataFrame([dict(row) for row in results])
        df.insert(loc=0, column="download", value=False)
        edited_df=st.data_editor(df[status_col_order].rename(columns={'SN_status_update_timestamp': 'update_timestamp'}),disabled=[x for x in status_col_order if x!='download'])
        not_existed_file=[]
        list_files=[]
        if edited_df["download"].any():
            for x in edited_df[edited_df['download']]['BBBG'].to_list():
                if os.path.isfile(os.path.join(conf['OUTPUT_DIR'], selected_hopdong, 'ATP',f'ATP_{x}.docx')):
                    list_files.append(os.path.join(conf['OUTPUT_DIR'], selected_hopdong, 'ATP',f'ATP_{x}.docx'))
                elif os.path.isfile(os.path.join(conf['OUTPUT_DIR'], selected_hopdong, 'ATP Template',f'ATP_{x}.docx')):
                    list_files.append(os.path.join(conf['OUTPUT_DIR'], selected_hopdong, 'ATP Template',f'ATP_{x}.docx'))
                else:
                    not_existed_file.append(x)
            atp_card_zip_buffer = zip_files(list_files)
        if not_existed_file:
            st.error(f"List file atp not existed because no host in: {not_existed_file}")
    else:
        edited_df=st.data_editor(pd.DataFrame(columns=status_col_order), disabled=status_col_order)
    st.download_button(
            label="Download selected files as ZIP",
            data=atp_card_zip_buffer,
            file_name="selected_files.zip",
            mime="application/zip",
            disabled=not edited_df["download"].any()
        )

    st.subheader('Download ATP ngoai quan')
    atp_apperance_zip_buffer=''
    selected_hopdong_download = st.selectbox("Hopdong", get_list_hd(database=db_path), label_visibility="visible", key='hopdong_download')
    if selected_hopdong_download:
        atp_apperance_zip_buffer = zip_files(glob(os.path.join(conf['OUTPUT_DIR'], selected_hopdong_download, 'ATP Appearance','*.docx')))
    st.download_button(
        label="Download selected files as ZIP",
        data=atp_apperance_zip_buffer,
        file_name=f"ATP_ngoai_quan_{selected_hopdong_download}.zip",
        mime="application/zip",
        disabled=not selected_hopdong_download
    )

    st.subheader('Serial Number Planning')
    col1, col2, col0 = st.columns([2.5,3,4.5])
    with col1:
        selected_hopdong_planning = st.selectbox(
            "Hopdong", get_list_hd(database=db_path), label_visibility="visible", key='hopdong_planning')
    with col2:
        host_options = get_list_host(database=db_path, hd=selected_hopdong_planning)
        all_host_options = ["All"] + host_options
        selected_host_planning = st.multiselect("Hostname", all_host_options, label_visibility="visible", default=['All'], key='host_planning')
    if selected_host_planning:
        query = "SELECT Hostname, SN, PlannedSlot, RealSlot, InstallationStatus FROM checkSN WHERE PlannedSlot IS NOT NULL AND ma_HD=?"
        params = [selected_hopdong_planning]
        if "All" not in selected_host_planning:
            host_placeholders = ','.join(['?'] * len(selected_host_planning))
            query+=f" AND Hostname IN ({host_placeholders})"
            params.append(selected_host_planning)
        df = pd.read_sql_query(query, conn, params=params)
        st.dataframe(df)
    conn.close()

else:
    st.subheader('Serial Number ATP Status Dashboard')
    col1, col2, col3, col0 = st.columns([2.5,3,1.5,3])
    with col1:
        st.selectbox("Hopdong", [], label_visibility="visible", key='hopdong_status')
    with col2:
        st.multiselect("BBBG", [], label_visibility="visible", key='bbbg_status')
    with col3:
        st.multiselect("Status",[], label_visibility="visible", key='state_status')
    st.dataframe(pd.DataFrame(columns=status_col_order))
    st.subheader('Download ATP ngoai quan')
    st.selectbox("Hopdong", [], label_visibility="visible", key='hopdong_download')
    st.subheader('Serial Number Planning')
    col1, col2, col0 = st.columns([2.5,3,4.5])
    with col1:
        st.selectbox("Hopdong", [], label_visibility="visible", key='hopdong_planning')
    with col2:
        st.multiselect("Hostname", [], label_visibility="visible", key='host_planning')
    st.dataframe(pd.DataFrame(columns=['Hostname', 'SN', 'PlannedSlot','RealSlot', 'InstallationStatus']))