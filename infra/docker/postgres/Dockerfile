FROM postgis/postgis:16-3.5@sha256:7ef699637304feff96028edbc7a653e135f2db2236d322b5cb2bfca11fd920bc

ARG PGVECTOR_VERSION=0.8.6
RUN sed -i -e 's|http://deb.debian.org|https://deb.debian.org|g' \
    -e 's|http://security.debian.org|https://security.debian.org|g' \
    /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true \
    && printf '%s\n' \
       'deb https://snapshot.debian.org/archive/debian/20250721T000000Z bullseye main' \
       'deb https://snapshot.debian.org/archive/debian-security/20250721T000000Z bullseye-security main' \
       'deb https://snapshot.debian.org/archive/debian/20250721T000000Z bullseye-updates main' \
       > /etc/apt/sources.list \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install -y --no-install-recommends ca-certificates build-essential postgresql-server-dev-16 git \
    && git clone --branch v${PGVECTOR_VERSION} --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector \
    && make -C /tmp/pgvector install \
    && rm -rf /tmp/pgvector \
    && apt-get purge -y --auto-remove build-essential git postgresql-server-dev-16 \
    && rm -rf /var/lib/apt/lists/*
