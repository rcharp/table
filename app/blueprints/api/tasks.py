from app.app import create_celery_app, db

celery = create_celery_app()


@celery.task()
def generate_drops():
    return