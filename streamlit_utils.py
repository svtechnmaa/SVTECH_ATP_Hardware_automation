import streamlit as st
import sys
import os
import logging
import random
import time
from contextlib import contextmanager

class SafeBuffer:
    '''
    In-memory line buffer to safely append log lines.
    Replaces StringIO — avoids I/O closed errors on rerun or async update.
    Holds only latest max_lines to prevent runaway memory.
    .write() = extend line-by-line
    .getvalue() = reassemble into string for display
    '''
    def __init__(self, max_lines=1000):
        self.lines = []
        self.max_lines = max_lines

    def write(self, s):
        self.lines.extend(s.splitlines(keepends=True))
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]

    def getvalue(self):
        return ''.join(self.lines)

    def flush(self):
        pass

    def close(self):
        self.lines = []

@contextmanager
def st_redirect(src_data_stream, display_type, display_container, src_name, cache_data, max_lines):
    '''
    src_data_stream: the data to be displayed on streamlit container, we will specify either sys.stdout or sys.stderr obj here
    display_type: the streamlit component type to store the src data (text box, code, header, whatever)
    display_container: the streamlit larger container to help navigate to the container that stores the src data (tab, sidebar, etc.)
    src_name: name of "src", to store as key in streamlit session_state (since in Python there's no clean way to access a variable name by itself)
    '''
    if all(v is not None for v in [src_data_stream, display_type, display_container, src_name, cache_data]):
        pass

    placeholder = display_container.empty()
    output_func = getattr(placeholder, display_type)

    # - We will use the source data stream's name as key to store the stream data in streamlit cache,
    # - in case we want to save this log or console output somewhere else
    # - initiation will be done regardless of whether cache is True or False to avoid complication
    if src_name not in st.session_state:
        st.session_state[src_name] = ""

    buffer = SafeBuffer(max_lines=max_lines)

    # if cache_data is True, we restore previous log from session_state to buffer to maintain log continuity across rerun.
    # we also force a display update with output_func(...) so user sees the last log immediately — even before new writes come in.

    if cache_data:
        buffer.write(st.session_state.get(src_name, ""))
        output_func(buffer.getvalue())
    old_write = src_data_stream.write

    # This function overrides the write() method of sys.stdout/sys.stderr
    # Appends to session_state (if enabled)
    # Always pushes current buffer into display
    # Only called when Streamlit is actively running the script — ignored in background threads or non-UI mode
    def new_write(b):
        try:
            if cache_data:
                st.session_state[src_name] += b
            buffer.write(b)
            output_func(buffer.getvalue())
        except Exception:
            old_write(b)

    try:
        src_data_stream.write = new_write
        yield
    finally:
        src_data_stream.write = old_write
        buffer.close()

@contextmanager
def st_stdout(display_type, display_container, cache_data=False, max_lines=1000):
    with st_redirect(sys.stdout, display_type, display_container, "sys.stdout", cache_data, max_lines):
        yield

@contextmanager
def st_stderr(display_type, display_container, cache_data=False, max_lines=1000):
    with st_redirect(sys.stderr, display_type, display_container, "sys.stderr", cache_data, max_lines):
        yield

# --- Logging Initialization ---
def LOGGER_INIT(log_level=logging.INFO,
                log_file='unconfigured_log.log',
                file_size=2 * 1024 * 1024,
                file_count=2,
                shell_output=False,
                log_file_mode='a',
                log_format='%(asctime)s %(levelname)s %(funcName)s(%(lineno)d)     %(message)s',
                print_log_init=False):

    try:
        main_logger = logging.getLogger()
        main_logger.setLevel(log_level)
        log_formatter = logging.Formatter(log_format)
    except Exception as e:
        print(f"Error formatting logger: {e}")

    log_dir = os.path.dirname(os.path.abspath(log_file))
    if print_log_init:
        print(f"Creating log directory ({log_dir})")

    try:
        main_logger.handlers = []
        main_logger.propagate = False
        from logging.handlers import RotatingFileHandler
        log_rotate_handler = RotatingFileHandler(log_file, mode=log_file_mode,
                                                 maxBytes=file_size, backupCount=file_count)
        log_rotate_handler.setFormatter(log_formatter)
        log_rotate_handler.setLevel(log_level)
        main_logger.addHandler(log_rotate_handler)
    except Exception as e:
        print(f"Exception setting up rotating handler: {e}")

    try:
        os.makedirs(log_dir, exist_ok=True)
        stream_log_handler = logging.StreamHandler(stream=sys.stdout if shell_output else sys.stderr)
        stream_log_handler.setFormatter(log_formatter)
        stream_log_handler.setLevel(log_level)
        main_logger.addHandler(stream_log_handler)
    except Exception as e:
        print(f"Exception setting up stream handler: {e}")

    noisy_loggers = [
        "watchdog.observers.inotify_buffer",
        "urllib3.connectionpool",
        "asyncio",
        "streamlit.runtime.scriptrunner.script_runner"
    ]
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.INFO)

    if print_log_init:
        print(f"Done, logging level {log_level} to {os.path.abspath(log_file)}")

# --- Demo Spam Buttons ---
def spam_logs():
    for i in range(random.randint(10, 20)):
        logging.debug(f"Debug log {i}: something random happened")
        logging.info(f"Info log {i}: operation succeeded")
        logging.warning(f"Warning log {i}: something might be wrong")
        time.sleep(0.1)

def spam_prints():
    for i in range(random.randint(10, 20)):
        print(f"This is a test print message #{i}")
        time.sleep(0.1)

# --- Main Streamlit App UI ---
def run_demo_ui():
    st.title("Log Display Modes")
    option = st.sidebar.radio("Choose Display Mode:", [
        "Same Tab: All Logs",
        "Popup: Split Logs",
        "Tabs: STDOUT & STDERR",
        "MainOperation: Inline Output"
    ])

    retain_logs = st.sidebar.checkbox("Retain logs after rerun", value=False)
    max_log_lines = st.sidebar.slider("Max lines to keep in log view", 100, 5000, 1000)

    LOGGER_INIT(log_level=logging.DEBUG, print_log_init=False, shell_output=(option == "Same Tab: All Logs"))

    if option == "Same Tab: All Logs":
        MainOperation, BackendLog = st.tabs(["MainOperation", "BackendLog"])
        with st_stdout("code", BackendLog, cache_data=retain_logs, max_lines=max_log_lines), \
             st_stderr("code", BackendLog, cache_data=retain_logs, max_lines=max_log_lines):
            with MainOperation:
                if st.button("Spam Logs"):
                    spam_logs()
                if st.button("Spam Prints"):
                    spam_prints()
                st.write("Try pressing the buttons above to generate output.")
            with BackendLog:
                st.subheader("With this style, both PRINT and LOG will be displayed on this tab")

    elif option == "Popup: Split Logs":
        MainColumn, PopupColumn = st.columns([10, 3])
        with PopupColumn:
            TerminalOutput = st.popover("TerminalOutput")
            LoggingOutput = st.popover("LoggingOutput")
            with TerminalOutput:
                st.subheader("Python printing operation (STDOUT) will be displayed on this tab")
            with LoggingOutput:
                st.subheader("Python Logging operation (STDERR) will be displayed on this tab")
        with MainColumn:
            with st_stdout("code", TerminalOutput, cache_data=retain_logs, max_lines=max_log_lines), \
                 st_stderr("code", LoggingOutput, cache_data=retain_logs, max_lines=max_log_lines):
                if st.button("Spam Logs"):
                    spam_logs()
                if st.button("Spam Prints"):
                    spam_prints()
                st.write("Try pressing the buttons above to generate output.")

    elif option == "Tabs: STDOUT & STDERR":
        MainOperation, TerminalOutput, LoggingOutput = st.tabs(["MainOperation", "TerminalOutput", "LogData"])
        with st_stdout("code", TerminalOutput, cache_data=retain_logs, max_lines=max_log_lines), \
             st_stderr("code", LoggingOutput, cache_data=retain_logs, max_lines=max_log_lines):
            with MainOperation:
                if st.button("Spam Logs"):
                    spam_logs()
                if st.button("Spam Prints"):
                    spam_prints()
                st.write("Try pressing the buttons above to generate output.")
            with TerminalOutput:
                st.subheader("Python PRINTING OPERATION (STDOUT) will be displayed on this tab")
            with LoggingOutput:
                st.subheader("Python LOGGING DATA from logger object will be displayed on this tab")

    elif option == "MainOperation: Inline Output":
        st.subheader("Main Operation with Inline Logs Displayed Below")

        # Create all 4 placeholders
        spam_logs_placeholder = st.empty()
        spam_prints_placeholder = st.empty()
        stdout_placeholder = st.empty()
        stderr_placeholder = st.empty()

        with st_stdout("code", stdout_placeholder, cache_data=retain_logs, max_lines=max_log_lines), \
             st_stderr("code", stderr_placeholder, cache_data=retain_logs, max_lines=max_log_lines):
            
            with spam_logs_placeholder.container():
                if st.button("Spam Logs"):
                    spam_logs()

            with spam_prints_placeholder.container():
                if st.button("Spam Prints"):
                    spam_prints()

            st.write("Try pressing the buttons above to generate output.")

# --- Direct Run Mode ---
if __name__ == "__main__":
    run_demo_ui()
