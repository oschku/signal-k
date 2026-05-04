FROM signalk/signalk-server:latest

# The base image's entrypoint (/home/node/signalk/startup.sh) runs
# `signalk-server --securityenabled` with no --configdir, so signalk-server
# falls back to the WORKDIR /home/node/.signalk as its config directory.
# Our signalk-config/ files therefore must land at /home/node/.signalk/, and
# the plugins at /home/node/plugins/ so that file:../plugins/* refs in
# signalk-config/package.json resolve correctly.

USER root

# Clear any defaults the base image left in the config dir
RUN rm -rf /home/node/.signalk/* /home/node/.signalk/.[!.]* 2>/dev/null || true

COPY --chown=node:node signalk-config/ /home/node/.signalk/
COPY --chown=node:node plugins/        /home/node/plugins/

# Replicate the panasonic-user KIP dashboard config to the admin user (the
# default user on a fresh secure-mode container) so the dashboards show up
# wherever you log in.
RUN mkdir -p /home/node/.signalk/applicationData/users/admin/kip && \
    cp /home/node/.signalk/applicationData/users/panasonic/kip/11.0.0.json \
       /home/node/.signalk/applicationData/users/admin/kip/11.0.0.json && \
    chown -R node:node /home/node/.signalk/applicationData/users/admin

USER node

# Install plugin internal deps FIRST — when signalk-config's npm install
# creates file: symlinks into ../plugins, those plugin dirs need to already
# carry their own node_modules (signalk-solunar pulls in suncalc).
WORKDIR /home/node/plugins/signalk-solunar
RUN npm install --omit=dev

WORKDIR /home/node/plugins/signalk-slippage
RUN npm install --omit=dev

WORKDIR /home/node/plugins/signalk-fuel-monitor
RUN npm install --omit=dev

# Install everything signalk-config/package.json declares — registry plugins
# (KIP, freeboard-sk, derived-data, …) and file: symlinks to our plugins.
WORKDIR /home/node/.signalk
RUN npm install --omit=dev

# Build-time verification — fail loudly here if anything's missing rather
# than producing a silently-broken container.
RUN set -e && \
    echo "Verifying custom plugins..." && \
    test -e node_modules/signalk-fuel-monitor/package.json && \
    test -e node_modules/signalk-slippage/package.json && \
    test -e node_modules/signalk-solunar/package.json && \
    echo "Verifying signalk-solunar's suncalc dep..." && \
    test -e /home/node/plugins/signalk-solunar/node_modules/suncalc/package.json && \
    echo "Verifying registry plugins..." && \
    test -e node_modules/@mxtommy/kip/package.json && \
    test -e node_modules/@signalk/freeboard-sk/package.json && \
    test -e node_modules/signalk-derived-data/package.json && \
    echo "Verifying KIP dashboards..." && \
    test -e applicationData/users/admin/kip/11.0.0.json && \
    test -e applicationData/users/panasonic/kip/11.0.0.json && \
    echo "All plugins, deps, and dashboards verified OK."

# Inherit ENTRYPOINT and WORKDIR from the base image — startup.sh launches
# signalk-server in /home/node/.signalk automatically, with --securityenabled.
