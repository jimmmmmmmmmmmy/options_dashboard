FROM python:3.13
RUN pip install poetry
WORKDIR /dashboard_app
COPY pyproject.toml poetry.lock* /dashboard_app/
RUN poetry config virtualenvs.create false && poetry install --no-dev
COPY lib /dashboard_app/lib
COPY assets /dashboard_app/assets
COPY dashboard_app /dashboard_app/dashboard_app
ADD dashboard.py .
ARG api_key
ENV POLYGON_API_KEY=$api_key
EXPOSE 8050
CMD ["python", "./dashboard.py", "--docker"]