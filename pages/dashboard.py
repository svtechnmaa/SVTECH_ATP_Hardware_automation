import streamlit as st
from utils import *

conf=read_conf()
db_path=os.path.join(conf['OUTPUT_DIR'], conf['DB_NAME'])
st.header('Serial Number ATP Status Dashboard')
col1, col2, col3, col0 = st.columns([2.5,3,1.5,3])
with col1:
    selected_hopdong = st.selectbox(
        "Hopdong", get_list_hd(database=db_path), label_visibility="visible")
with col2:
    bbbg_options = get_list_bbbg(database=db_path, hd=selected_hopdong)
    all_bbbg_options = ["All"] + bbbg_options
    selected_bbbg = st.multiselect("BBBG", all_bbbg_options, label_visibility="visible", default=['All'])
with col3:
    status_options=['Unchecked', 'Not-Installed', 'Installed', 'Checked', 'Checked with reboot', 'Checked without reboot']
    all_status_options = ["All"] + status_options
    selected_status = st.multiselect("Status",all_status_options, label_visibility="visible", default=['All'])
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

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

conn.close()
st.markdown(
            f"""
            <style>
            .stTable table {{
                font-size: 0.8em; /* Adjust this to your desired font size */
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
st.dataframe(pd.DataFrame([dict(row) for row in results]))
