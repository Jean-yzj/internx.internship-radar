FROM caddy:2-alpine

WORKDIR /srv
COPY index.html /srv/
COPY data /srv/data

EXPOSE 8080

CMD ["caddy", "file-server", "--root", "/srv", "--listen", ":8080", "--access-log"]
