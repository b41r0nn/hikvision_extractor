FROM nginx:alpine

# openssl para generar el certificado autofirmado en tiempo de build
RUN apk add --no-cache openssl

# Generar certificado autofirmado válido por 3650 días (10 años).
# Para IP local (sin dominio) – el CN es la IP del servidor.
# Los navegadores mostrarán advertencia de certificado, lo cual es normal
# para redes internas sin CA. El usuario puede aceptarlo manualmente.
RUN mkdir -p /etc/nginx/ssl && \
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/server.key \
        -out    /etc/nginx/ssl/server.crt \
        -subj   "/CN=192.168.1.250/O=REDIHOS SAS/C=CO" \
        -addext "subjectAltName=IP:192.168.1.250,IP:127.0.0.1"

# Configuración nginx con SSL y proxy /api/
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Archivos estáticos del panel web
COPY . /usr/share/nginx/html

EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]
