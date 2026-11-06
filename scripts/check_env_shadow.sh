   #!/usr/bin/env bash
   # Lista las variables del shell que pisan al .env (Docker Compose prioriza el entorno).
   # Nunca imprime valores: solo nombres y si el valor es igual o distinto.
   set -euo pipefail
   cd "$(git rev-parse --show-toplevel)"
   ENVFILE="${1:-.env}"
   [ -f "$ENVFILE" ] || { echo "ERROR: no existe $ENVFILE" >&2; exit 2; }

   conflicts=0
   while IFS= read -r line; do
     line="${line%$'\r'}"
     [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
     name="${BASH_REMATCH[1]}"
     val="${BASH_REMATCH[2]}"
     if [[ "$val" =~ ^\"(.*)\"$ ]] || [[ "$val" =~ ^\'(.*)\'$ ]]; then val="${BASH_REMATCH[1]}"; fi
     if [ -n "${!name+x}" ]; then
       if [ "${!name}" = "$val" ]; then
         echo "igual    $name (en el shell, mismo valor que el .env)"
       else
         echo "PISA     $name (el valor del shell difiere del .env)"
         conflicts=$((conflicts+1))
       fi
     fi
   done < "$ENVFILE"

   if [ "$conflicts" -gt 0 ]; then
     echo "RESULTADO: $conflicts variable(s) del shell pisan al .env. Haz unset de esas variables y abre una terminal nueva." >&2
     exit 1
   fi
   echo "RESULTADO: ninguna variable del shell pisa al .env"