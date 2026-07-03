import os
import random
import shlex
import shutil
import string
import subprocess

try:
    # Inspired by
    # https://github.com/django/django/blob/master/django/utils/crypto.py
    random = random.SystemRandom()
    using_sysrandom = True
except NotImplementedError:
    using_sysrandom = False

TERMINATOR = "\x1b[0m"
WARNING = "\x1b[1;33m [WARNING]: "
INFO = "\x1b[1;33m [INFO]: "
HINT = "\x1b[3;33m"
SUCCESS = "\x1b[1;32m [SUCCESS]: "


create_nextjs_frontend = "{{ copier__create_nextjs_frontend }}"
if create_nextjs_frontend == "False":
    shutil.rmtree("frontend")
    file_names = [
        os.path.join("k8s", "base", "frontend.yaml"),
        os.path.join(
            "argocd",
            "base",
            "{{ copier__project_slug }}",
            "cloudfront-invalidation-hook.yaml",
        ),
    ]
    for file_name in file_names:
        os.remove(file_name)
else:
    subprocess.run(shlex.split("make init-frontend-dependencies"), check=True)


def remove_celery_files():
    file_names = [
        os.path.join("backend", "{{ copier__project_slug }}", "celery_app.py"),
        os.path.join("backend", "{{ copier__project_slug }}", "users", "tasks.py"),
        os.path.join(
            "backend",
            "{{ copier__project_slug }}",
            "users",
            "tests",
            "test_tasks.py",
        ),
        os.path.join("k8s", "base", "celery.yaml"),
        os.path.join("k8s", "base", "flower.yaml"),
    ]
    for file_name in file_names:
        os.remove(file_name)


def remove_bitbucket_files():
    # If 'source_control_provider' is not 'bitbucket' remove related files
    file_names = ["bitbucket-pipelines.yml"]
    for file_name in file_names:
        os.remove(file_name)


def remove_github_files():
    # If 'source_control_provider' is not 'github' remove related files
    shutil.rmtree(".github")


def append_to_project_gitignore(path):
    gitignore_file_path = ".gitignore"
    with open(gitignore_file_path, "a") as gitignore_file:
        gitignore_file.write(path)
        gitignore_file.write(os.linesep)


def generate_random_string(
    length, using_digits=False, using_ascii_letters=False, using_punctuation=False
):
    """
    Example:
        opting out for 50 symbol-long, [a-z][A-Z][0-9] string
        would yield log_2((26+26+50)^50) ~= 334 bit strength.
    """
    if not using_sysrandom:
        return None

    symbols = []
    if using_digits:
        symbols += string.digits
    if using_ascii_letters:
        symbols += string.ascii_letters
    if using_punctuation:
        all_punctuation = set(string.punctuation)
        # These symbols can cause issues in environment variables
        unsuitable = {"'", '"', "\\", "$"}
        suitable = all_punctuation.difference(unsuitable)
        symbols += "".join(suitable)
    return "".join([random.choice(symbols) for _ in range(length)])


def set_flag(file_path, flag, value=None, formatted=None, *args, **kwargs):
    if value is None:
        random_string = generate_random_string(*args, **kwargs)
        if random_string is None:
            print(
                "We couldn't find a secure pseudo-random number generator on your system. "
                "Please, make sure to manually {} later.".format(flag)
            )
            random_string = flag
        if formatted is not None:
            random_string = formatted.format(random_string)
        value = random_string

    with open(file_path, "r+") as f:
        file_contents = f.read().replace(flag, value)
        f.seek(0)
        f.write(file_contents)
        f.truncate()

    return value


def set_django_secret_key(file_path):
    django_secret_key = set_flag(
        file_path,
        "__DJANGO_SECRET_KEY__",
        length=64,
        using_digits=True,
        using_ascii_letters=True,
    )
    return django_secret_key


def set_postgres_password(file_path, value=None):
    postgres_password = set_flag(
        file_path,
        "__POSTGRES_PASSWORD__",
        value=value,
        length=64,
        using_digits=True,
        using_ascii_letters=True,
    )
    return postgres_password


def append_to_gitignore_file(s):
    with open(".gitignore", "a") as gitignore_file:
        gitignore_file.write(s)
        gitignore_file.write(os.linesep)


def set_flags_in_secrets():
    local_secrets_path = os.path.join("k8s", "local", "secrets.yaml")
    set_django_secret_key(os.path.join("k8s", "local", "secrets.yaml"))
    set_postgres_password(local_secrets_path)


def remove_sentry_files():
    os.remove(os.path.join("docs", "sentry.md"))


def remove_graphql_files():
    os.remove(os.path.join("backend", "config", "schema.py"))
    os.remove(
        os.path.join(
            "backend",
            "{{ copier__project_slug }}",
            "users",
            "mutations.py",
        )
    )
    os.remove(
        os.path.join(
            "backend",
            "{{ copier__project_slug }}",
            "users",
            "queries.py",
        )
    )
    os.remove(
        os.path.join(
            "backend",
            "{{ copier__project_slug }}",
            "users",
            "types.py",
        )
    )
    os.remove(
        os.path.join(
            "backend",
            "{{ copier__project_slug }}",
            "users",
            "tests",
            "test_graphql_views.py",
        )
    )


def init_git_repo():
    print(INFO + "Initializing git repository..." + TERMINATOR)
    print(INFO + f"Current working directory: {os.getcwd()}" + TERMINATOR)
    subprocess.run(
        shlex.split("git -c init.defaultBranch=main init . --quiet"), check=True
    )
    print(SUCCESS + "Git repository initialized." + TERMINATOR)


def configure_git_remote():
    repo_url = "{{ copier__repo_url }}"
    if repo_url:
        print(INFO + f"repo_url: {repo_url}" + TERMINATOR)
        command = f"git remote add origin {repo_url}"
        subprocess.run(shlex.split(command), check=True)
        print(SUCCESS + f"Remote origin={repo_url} added." + TERMINATOR)
    else:
        print(
            WARNING
            + "No repo_url provided. Skipping git remote configuration."
            + TERMINATOR
        )


def party_popper():
    for _ in range(4):
        print("\r🎉 POP! 💥", end="", flush=True)
        subprocess.run(["sleep", "0.3"])
        print("\r💥 POP! 🎉", end="", flush=True)
        subprocess.run(["sleep", "0.3"])

    print("\r🎊 Congrats! Your {{ copier__project_slug }} project is ready! 🎉")
    print()
    print("To get started, run:")
    print("cd {{ copier__project_slug }}")
    print("tilt up")
    print()


def run_setup():
    subprocess.run(
        shlex.split("kind create cluster --name {{ copier__project_dash }}"), check=True
    )
    subprocess.run(shlex.split("make compile"), check=True)

    print("Dependencies compiled successfully.")
    print("Performing initial commit.")

    subprocess.run(shlex.split("git add ."), check=True)
    subprocess.run(shlex.split("git commit -m 'Initial commit' --quiet"), check=True)


def main():
    set_flags_in_secrets()

    if "{{ copier__use_celery }}" != "True":
        remove_celery_files()

    if "{{ copier__source_control_provider }}" != "bitbucket.org":
        remove_bitbucket_files()

    if "{{ copier__source_control_provider }}" != "github.com":
        remove_github_files()

    if "{{ copier__use_sentry }}" == "False":
        remove_sentry_files()

    if "{{ copier__create_nextjs_frontend }}" == "False":
        remove_graphql_files()

    # Format code using black and isort (versions should match .pre-commit-config.yaml)
    subprocess.run(shlex.split("black ./backend"), check=True)
    subprocess.run(shlex.split("isort --profile=black ./backend"), check=True)

    init_git_repo()
    configure_git_remote()
    run_setup()
    party_popper()

    print(SUCCESS + "Project initialized, keep up the good work!!" + TERMINATOR)


if __name__ == "__main__":
    main()
