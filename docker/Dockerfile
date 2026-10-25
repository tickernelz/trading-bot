FROM freqtrade-base AS engine
USER ftuser
RUN pip install --user --no-cache-dir pyyaml==6.0.3
WORKDIR /opt/trading-bot
COPY --chown=ftuser:ftuser engine ./engine
ENV PYTHONPATH=/opt/trading-bot \
    TRADING_BOT_CONFIG=/opt/trading-bot/config/config.yaml \
    TRADING_BOT_USERDIR=/freqtrade/user_data
ENTRYPOINT ["python", "-m", "engine.launch"]
CMD ["trade"]

FROM engine AS test
RUN pip install --user --no-cache-dir pytest==9.1.1
COPY --chown=ftuser:ftuser pyproject.toml ./
COPY --chown=ftuser:ftuser config/config.example.yaml ./config/config.example.yaml
COPY --chown=ftuser:ftuser tests ./tests
ENTRYPOINT ["python", "-m", "pytest"]
CMD []
