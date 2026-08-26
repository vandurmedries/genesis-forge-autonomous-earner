FROM apify/actor-python:3.12

COPY --chown=myuser:myuser requirements-apify.txt ./requirements-apify.txt
RUN pip install --no-cache-dir -r requirements-apify.txt

COPY --chown=myuser:myuser capi2 ./capi2
COPY --chown=myuser:myuser actor_main.py ./actor_main.py

ENV CAPI2_AGENT402_REGISTER=false
ENV CAPI2_TRUE402_REGISTER=false

CMD ["python", "actor_main.py"]
