import os

EXCLUDED_DIRS = {".venv", ".idea", "__pycache__", ".git"}
EXCLUDED_FILES = {".gitignore"}


def build_tree(path, prefix=""):
    entries = sorted(
        e for e in os.listdir(path)
        if e not in EXCLUDED_FILES and not e.startswith(".")
    )

    tree_str = ""

    for index, entry in enumerate(entries):
        full_path = os.path.join(path, entry)

        if os.path.isdir(full_path) and entry in EXCLUDED_DIRS:
            continue

        connector = "`-- " if index == len(entries) - 1 else "|-- "
        tree_str += prefix + connector + entry + "\n"

        if os.path.isdir(full_path):
            extension = "    " if index == len(entries) - 1 else "|   "
            tree_str += build_tree(full_path, prefix + extension)

    return tree_str


def write_tree_to_file(root_path, output_file="tree.txt"):
    if not os.path.exists(root_path):
        print(f"Path does not exist: {root_path}")
        return

    tree = root_path + "/\n" + build_tree(root_path)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(tree)

    print(f"Tree file created: {output_file}")


def main():
    project_path = r"C:\Users\CyberZone\PycharmProjects\shop_project"
    write_tree_to_file(project_path)


if __name__ == "__main__":
    main()
