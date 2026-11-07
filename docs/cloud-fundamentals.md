# Fundamentos de nube: mapa de mis piezas

| Campo | Valor |
|---|---|
| Autor | Rodrigo Codoceo |
| Semana | 2 del plan maestro (2 a 7-nov-2026) |
| Lecturas | DDIA cap. 1 §, IAC caps. 1 y 2 §, CWC cap. 4 §, más documentación oficial de AWS |
| Estado | Esqueleto: se completa con lo que leas, en tus palabras |

Regla: cada celda se llena con lo que entendiste y puedes explicar en 2 minutos. Si no lo puedes explicar, vuelve a leer. No copies texto de los libros ni de la documentación.

## 1. Regiones y zonas de disponibilidad

- **Qué es, en mis palabras:**
R: Una región es un área geográfica donde el proveedor tiene centros de datos. Dentro hay varias zonas de disponibilidad: lugares aislados, con energía, enfriamiento y red propios. Si una zona falla, las otras de la región siguen funcionando, pero el traslado no es automático: yo debo repartir mi aplicación en varias zonas (o usar un servicio que lo haga).
- **Dónde aparece en mi repo hoy:** (pista: un solo clúster, un solo nodo de Postgres, un solo host)
R:   Hoy todo corre en una sola máquina: kind (sus 3 nodos son 3 contenedores del mismo PC), un Postgres en Docker y un webhook de 1 réplica. Si el PC se apaga, cae todo. No hay zonas ni regiones.
- **Qué haría distinto en la nube:**
R:   Al menos 2 zonas; réplicas del webhook repartidas por zona (en el deployment cambiaría el topologyKey de kubernetes.io/hostname a topology.kubernetes.io/zone); base con réplica en otra zona. Más zonas cuestan más (tráfico entre zonas), así que solo lo que se justifique, y destruir todo al terminar el día.
- **Fuente:**
R: DDIA 1 (pp. 19-20: latencia, tolerancia a fallas, residencia de datos), CWC 4 (recuadro de regiones y zonas).

## 2. Responsabilidad compartida

- **Qué es, en mis palabras:**
R:   Es un reparto de tareas: el proveedor cuida lo que está debajo (edificios, hardware, virtualización) y yo lo que pongo encima (datos, accesos, configuración, aplicación). Cuánto cubre cada uno cambia según el modelo: en IaaS manejo más, en PaaS menos y en SaaS casi nada (CWC 4, Figura 4-1). El costo es menos control y menos visibilidad: no veo el sistema operativo y, si el servicio cae, solo espero. Lo que no delego: mis datos, mis claves y quién puede entrar (confirmarlo en la página del modelo de AWS).
- **Qué opero yo hoy y qué operaría el proveedor si el mismo stack estuviera en un servicio gestionado:**
R:   Hoy opero todo: el PC y Docker, el clúster kind, Postgres, Grafana, el webhook, los Secrets y los respaldos. En la nube con servicios gestionados (por ejemplo EKS y una base gestionada) el proveedor operaría el hardware y el plano de control de Kubernetes (y el motor de la base, según el servicio); yo seguiría con la aplicación, los manifiestos, los permisos, la red, los secretos y los datos. Cuánto de los nodos queda de mi lado lo confirmo en la documentación de EKS (semana 6).
- **Qué haría distinto en la nube:**
R:   Secretos en un gestor del proveedor (Secrets Manager) y no en archivos .env; roles con credenciales temporales en vez de claves fijas; alertas y logs propios desde el primer día, porque no tendré acceso al sistema operativo; vigilar el gasto (la planificación de capacidad pasa a ser planificación financiera, DDIA 1, p. 18).
- **Fuente:**
R: CWC 4 (Fig. 4-1), DDIA 1 (pp. 13-14 y 17-18) y la página del modelo de responsabilidad compartida de AWS, cuando la leas.

## 3. IAM (identidad y mínimo privilegio)

- **Qué es, en mis palabras:**
R: IAM controla quién puede hacer qué sobre qué recursos de AWS. Las identidades son usuarios, grupos y roles. Las políticas definen los permisos: por defecto todo está denegado y solo se permite lo que una política autoriza. Un rol no tiene clave fija: quien lo asume recibe credenciales temporales. IAM se puede conectar con proveedores externos de identidad (por ejemplo, para que un pipeline de GitHub use un rol sin guardar claves) y tiene herramientas para revisar cuentas y permisos
- **Dónde aparece en mi repo hoy:** (pista: Secrets de Kubernetes, tokens de Jira y Groq, la clave de Grafana, RBAC del clúster)
R: Hoy no uso IAM de nube, pero hay equivalentes. En Kubernetes, `webhook-sa` es una identidad sin token montado, y el rol `noc-operator` es una política de permisos mínimos (get, list, watch y patch de deployments) unida a su cuenta por un RoleBinding. En GitHub Actions, cada job declara sus `permissions:`. Y las credenciales viven en archivos `.env` y en Secrets de Kubernetes. Los tokens de Jira y Groq son de terceros: IAM no los gestiona. En AWS irían en Secrets Manager, e IAM decidiría quién puede leerlos.
- **Qué haría distinto en la nube:** (pista del plan: el pipeline asume un rol temporal, sin claves estáticas)
R: El pipeline asumiría un rol de IAM por OIDC: GitHub entrega un token firmado y AWS lo cambia por credenciales temporales que expiran solas, sin claves guardadas en GitHub. El rol solo confiaría en mi repositorio y tendría los permisos mínimos para desplegar. Los pods usarían roles propios en vez de claves. Y el usuario raíz llevaría doble factor y alarma de presupuesto.
- **Fuente:**
R: documentacion oficial de AWS.

## 4. VPC (red privada)

- **Qué es, en mis palabras:** (subredes, tablas de ruta, salida a internet)
R: Una VPC es mi red privada dentro de una región de AWS. Se divide en subredes, y cada subred vive en una sola zona de disponibilidad. Las tablas de ruta dicen por dónde sale el tráfico. Una subred es pública si su tabla tiene una ruta a un internet gateway. Una privada no la tiene y solo sale hacia internet a través de un NAT gateway. Entre subredes de la misma VPC el tráfico se enruta solo, sin gateway. El control se hace con dos capas: los security groups (por instancia, recuerdan las conexiones) y las NACL (por subred, sin memoria).
- **Dónde aparece en mi repo hoy:** (pista: `noc_net`, puertos publicados solo en 127.0.0.1, `host.docker.internal`)
R: `noc_net` es una red bridge de Docker en mi PC, no una VPC. Se parece a una red privada donde los contenedores se hablan por nombre. Los puertos publicados solo en `127.0.0.1` equivalen a un servicio sin ruta desde internet. La NetworkPolicy de `deploy/base/network-policy.yaml` (todo denegado y reglas de permiso) es lo más parecido a los security groups. Y `host.docker.internal` es la conexión entre dos redes distintas: el clúster kind y el Postgres de Docker.
- **Qué haría distinto en la nube:**
R: Subredes públicas y privadas en al menos 2 zonas. El balanceador de carga iría en las públicas; el webhook, Grafana y la base, en las privadas. La base solo aceptaría tráfico en el puerto 5432 desde el security group del webhook. Como el webhook llama a Jira y Groq, necesita salida a internet: un NAT gateway, que cobra por hora, así que lo destruiría cada día.
- **Fuente:**
R: documentacion oficial de AWS y CWC 4 (párrafo de red en IaaS)..

## 5. Almacenamiento

- **Qué es, en mis palabras:** (objetos, bloques, archivos: cuándo cada uno)
R: Hay tres tipos. Objetos (S3): archivos con una clave y metadatos, accesibles por API; muy duraderos y baratos; sirven para respaldos, multimedia y datos de análisis, pero no son un disco. Bloques (EBS): un disco virtual que se conecta a una instancia de una zona; sirve para bases de datos y sistemas de archivos con baja latencia, y puede seguir existiendo cuando la instancia se reemplaza. Archivos (EFS): un sistema de archivos compartido por varias instancias. Los discos locales de una instancia, en cambio, son efímeros (DDIA 1, p. 16).
- **Dónde aparece en mi repo hoy:** (pista: volumen `tsdb_data`, PVC de 2Gi del StatefulSet, respaldos con `pg_dump`)
R: En Compose, Postgres guarda sus datos en el volumen `tsdb_data` de Docker. En el clúster, el StatefulSet usa un PVC de 2Gi con la clase `standard`, que en kind es un directorio del nodo, dentro de mi PC. Los respaldos con `pg_dump` quedan en mi carpeta de usuario, en el mismo disco. Si el disco falla, se pierde todo, y todavía no probé restaurar un respaldo.
- **Qué haría distinto en la nube:**
R: Los datos de Postgres irían en un volumen EBS (a través del PVC) o en una base gestionada, no en S3: una base necesita un disco de baja latencia. Un volumen EBS vive en una sola zona, así que los pods deben programarse en esa zona, y la alta disponibilidad vendría de una réplica en otra. Los respaldos sí irían a S3, con retención por política de ciclo de vida, cifrado y un rol que solo pueda escribir en ese bucket. Y probaría la restauración.
- **Fuente:**
R: documentacion oficial de AWS y DDIA 1 (pp. 15-17) y CWC 4..

## 6. Mis piezas frente a AWS

La columna AWS parte de la tabla de equivalencias del plan maestro. Completa y corrige tras leer.

| Mi pieza hoy | Equivalente en AWS | Qué cambia al moverla | Qué riesgo nuevo aparece |
|---|---|---|---|
| Clúster kind | EKS | AWS opera el plano de control; yo sigo con los nodos de trabajo y las aplicaciones | Costo por hora del clúster y los nodos: hay que destruirlo cada día |
| Imagen en GHCR | ECR | El registro queda dentro de AWS y el nodo baja la imagen con un rol | Permisos de lectura o escritura demasiado amplios; costo de almacenamiento |
| Secrets de Kubernetes y `.env` | Secrets Manager | El valor vive en el servicio y se lee con un rol, no desde archivos | Dependencia del servicio; permisos de lectura demasiado amplios |
| Volumen de TimescaleDB y respaldos | EBS para el volumen, S3 para los respaldos (o una base gestionada) | Los datos salen del disco de mi PC y los respaldos tienen retención | EBS vive en una sola zona; un respaldo sin restauración probada no es un respaldo |
| Red `noc_net` y puertos | VPC con subredes públicas y privadas, y security groups | La base va en una subred privada y la entrada pública, solo por un balanceador | El NAT gateway cobra por hora; una regla abierta por error expone un servicio |
| Usuarios y claves de servicios | IAM (roles y credenciales temporales) | El pipeline y los pods asumen roles; no quedan claves fijas | Un rol con permisos de más |
| Webhook (`webhook-service`) | Deployment en EKS | Misma imagen, repartida en zonas | Más réplicas dependen de la misma base |
| Grafana | (completar en la semana 7, con CloudWatch) | | |

## 7. Preguntas que me quedan

trafico privado hacia APIs de AWS, Interface Endpoints AWS PrivateLink, Gateway Endpoints