import click

from ckanext.validation.model import create_tables, tables_exist


@click.group()
def validation():
    """Validation click command group"""
    pass


@validation.command()
@click.pass_context
def init_db(ctx):
    """Creates the necessary tables for validation in the database."""
    if tables_exist():
        click.secho(u"Validation tables already exist", fg="green")
        ctx.exit(0)

    create_tables()
    click.secho(u"Validation tables created", fg="green")


def get_commands():
    return [validation]
