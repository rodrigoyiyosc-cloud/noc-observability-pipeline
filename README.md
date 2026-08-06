# 📡 NOC Observability Pipeline

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=for-the-badge&logo=grafana&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2CA5E0?style=for-the-badge&logo=docker&logoColor=white)

Un pipeline de observabilidad de extremo a extremo diseñado para simular, ingerir, almacenar y visualizar telemetría de red en un entorno de Centro de Operaciones de Red (NOC). 

Este proyecto implementa una arquitectura basada en contenedores para transformar datos en bruto en inteligencia operativa accionable.

## 🏗️ Arquitectura del Sistema

El ecosistema está compuesto por tres capas principales, todas orquestadas mediante **Docker Compose**:

1. **Capa de Ingesta (Python Simulator):** Un simulador modular que genera métricas de red realistas (Latencia, Packet Loss, Uso de CPU) aplicando fluctuaciones estadísticas (*Gaussian jitter*) para emular el comportamiento de dispositivos Core y de Acceso.
2. **Capa de Almacenamiento (TimescaleDB/PostgreSQL):** Base de datos optimizada para series de tiempo. Utiliza *hyper-tables* y vistas materializadas para garantizar un rendimiento óptimo en la lectura y escritura masiva de datos.
3. **Capa de Visualización (Grafana OSS):** Dashboard interactivo aprovisionado mediante código (Infrastructure as Code - IaC). Se conecta dinámicamente a TimescaleDB para mostrar el estado de la red sin necesidad de configuración manual.

## 📂 Estructura del Proyecto

```text
├── python-simulator/
│   ├── main.py              # Script principal de ejecución
│   ├── config.py            # Variables de entorno y credenciales
│   └── database.py          # Lógica de conexión (Connection Pooling)
├── grafana-provisioning/
│   ├── datasources/         # Configuración automática de TimescaleDB
│   └── dashboards/          # Archivo JSON del dashboard principal
├── docker-compose.yml       # Orquestación de infraestructura
└── README.md
