from sqlalchemy import create_engine, Metadata


def db_engine():
    from flask import current_app
    conn = create_engine(current_app.config.get('SQLALCHEMY_DATABASE_URI'), client_encoding="UTF-8")
    return MetaData(bind=conn, reflect=True)