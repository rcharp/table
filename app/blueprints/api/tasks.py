from app.app import create_celery_app, db

celery = create_celery_app()


@celery.task()
def update_row(row, val, col):
    from app.blueprints.api.api_functions import update_row
    return update_row(row, val, col)
