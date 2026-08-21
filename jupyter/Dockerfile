FROM jupyter/scipy-notebook:latest

USER root

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

USER ${NB_UID}

WORKDIR /home/jovyan/work