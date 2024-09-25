FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

EXPOSE 5000

CMD [ "python3", "app.py" ]