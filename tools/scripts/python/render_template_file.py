import pathlib
import sys


def render_template_file(
    src: pathlib.Path,
    dest: pathlib.Path,
    db_name: str,
    db_user: str,
    db_pass: str,
    db_host_port: str,
    db_root_pass: str,
    project_slug: str,
    api_host_port: str,
    web_host_port: str,
    admin_host_port: str,
    proxy_host_port: str,
) -> None:
    text = src.read_text()
    text = text.replace("{{DB_NAME}}", db_name)
    text = text.replace("{{DB_USER}}", db_user)
    text = text.replace("{{DB_PASSWORD}}", db_pass)
    text = text.replace("{{DB_HOST_PORT}}", db_host_port)
    text = text.replace("{{DB_ROOT_PASSWORD}}", db_root_pass)
    text = text.replace("{{PROJECT_SLUG}}", project_slug)
    text = text.replace("{{API_HOST_PORT}}", api_host_port)
    text = text.replace("{{WEB_HOST_PORT}}", web_host_port)
    text = text.replace("{{ADMIN_HOST_PORT}}", admin_host_port)
    text = text.replace("{{PROXY_HOST_PORT}}", proxy_host_port)
    dest.write_text(text)


def main() -> int:
    if len(sys.argv) < 12:
        return 1
    src = pathlib.Path(sys.argv[1])
    dest = pathlib.Path(sys.argv[2])
    render_template_file(
        src=src,
        dest=dest,
        db_name=sys.argv[3],
        db_user=sys.argv[4],
        db_pass=sys.argv[5],
        db_host_port=sys.argv[6],
        db_root_pass=sys.argv[7] if len(sys.argv) > 7 else "",
        project_slug=sys.argv[8] if len(sys.argv) > 8 else "gptcreator",
        api_host_port=sys.argv[9] if len(sys.argv) > 9 else "3000",
        web_host_port=sys.argv[10] if len(sys.argv) > 10 else "5173",
        admin_host_port=sys.argv[11] if len(sys.argv) > 11 else "5174",
        proxy_host_port=sys.argv[12] if len(sys.argv) > 12 else "8080",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
