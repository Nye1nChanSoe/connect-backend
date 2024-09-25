FROM python:3.10-slim

# Install PostgreSQL development libraries
RUN apt-get update \
    && apt-get -y install libpq-dev gcc \
    && pip install psycopg2

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

EXPOSE 5000

CMD [ "python3", "app.py" ]