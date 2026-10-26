FROM freqtrade-base AS engine
USER ftuser
RUN pip install --user --no-cache-dir pyyaml==6.0.3
COPY --chown=ftuser:ftuser swarm /tmp/swarm
RUN pip install --user --no-cache-dir -c /tmp/swarm/constraints.txt /tmp/swarm && rm -rf /tmp/swarm
WORKDIR /opt/trading-bot
COPY --chown=ftuser:ftuser engine ./engine
COPY --chown=ftuser:ftuser gateway ./gateway
COPY --chown=ftuser:ftuser analytics ./analytics
ENV PYTHONPATH=/opt/trading-bot \
    TRADING_BOT_CONFIG=/opt/trading-bot/config/config.yaml \
    TRADING_BOT_USERDIR=/freqtrade/user_data
ENTRYPOINT ["python", "-m", "engine.launch"]
CMD ["trade"]

FROM engine AS test
RUN pip install --user --no-cache-dir pytest==9.1.1
COPY --chown=ftuser:ftuser pyproject.toml ./
COPY --chown=ftuser:ftuser config/config.example.yaml config/gateway.example.yaml ./config/
COPY --chown=ftuser:ftuser scripts/stage1.sh ./scripts/stage1.sh
COPY --chown=ftuser:ftuser tests ./tests
ENTRYPOINT ["python", "-m", "pytest"]
CMD []
