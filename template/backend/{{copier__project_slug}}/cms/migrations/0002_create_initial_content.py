from django.db import migrations


def create_content(apps, schema_editor):
    db = schema_editor.connection.alias
    Page = apps.get_model("wagtailcore", "Page")
    Site = apps.get_model("wagtailcore", "Site")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ContentPage = apps.get_model("cms", "ContentPage")

    # Historical models have no treebeard methods. This runs once on a new site.
    page_type = ContentType.objects.using(db).get(app_label="wagtailcore", model="page")
    Page.objects.using(db).filter(content_type=page_type, depth=2, slug="home").delete()
    content_type, _ = ContentType.objects.using(db).get_or_create(
        app_label="cms", model="contentpage"
    )
    root = Page.objects.using(db).get(depth=1)
    home = ContentPage.objects.using(db).create(
        title="Content",
        draft_title="Content",
        slug="home",
        intro="Your content starts here.",
        body="<p>Create and publish Content pages in the CMS to extend this site.</p>",
        content_type=content_type,
        locale_id=root.locale_id,
        path=root.path + "0001",
        depth=2,
        numchild=1,
        url_path="/home/",
        live=True,
    )
    ContentPage.objects.using(db).create(
        title="Example page",
        draft_title="Example page",
        slug="example",
        intro="This page is managed in Wagtail.",
        body="<p>Edit this page or publish another Content page to start building.</p>",
        content_type=content_type,
        locale_id=root.locale_id,
        path=home.path + "0001",
        depth=3,
        numchild=0,
        url_path="/home/example/",
        live=True,
    )
    Page.objects.using(db).filter(pk=root.pk).update(
        numchild=Page.objects.using(db)
        .filter(depth=2, path__startswith=root.path)
        .count()
    )
    Site.objects.using(db).update_or_create(
        is_default_site=True,
        defaults={"hostname": "localhost", "port": 80, "root_page_id": home.pk},
    )


class Migration(migrations.Migration):
    dependencies = [("cms", "0001_initial")]
    # Unapplying this data migration must not delete user-edited content.
    operations = [migrations.RunPython(create_content, migrations.RunPython.noop)]
