FROM apify/actor-python:3.12

COPY --chown=myuser:myuser requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=myuser:myuser scanner.py ./scanner.py
COPY --chown=myuser:myuser main.py ./main.py

CMD ["python", "main.py"]
