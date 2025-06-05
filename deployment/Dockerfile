FROM python:3.10.12-slim
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends libc6-dev make dpkg-dev git openssh-client libreoffice-common libreoffice-core libreoffice-writer \
    && apt-get clean all \
    && rm -rf /var/cache/apt/archives /var/lib/apt/lists/*
ARG git_token
ENV CONFIG_FILE="/opt/SVTECH_ATP_Hardware_automation/config.yaml"
RUN /usr/bin/git clone --branch main https://$git_token@github.com/svtechnmaa/SVTECH_ATP_Hardware_automation.git /opt/SVTECH_ATP_Hardware_automation
WORKDIR /opt/SVTECH_ATP_Hardware_automation
RUN pip install --no-cache-dir -r deployment/requirements.txt
RUN mkdir -p /opt/ATP_output_result
EXPOSE 8501
CMD ["streamlit", "run", "/opt/SVTECH_ATP_Hardware_automation/streamlit/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]