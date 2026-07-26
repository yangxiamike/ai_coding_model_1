"""zer0share 数据包命令行入口。"""
import argparse
import json

from data.dataset_package import build_dataset, build_standard_dataset, open_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or inspect immutable dataset packages")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build from a YAML dataset spec")
    build.add_argument("spec")
    standard = commands.add_parser(
        "build-standard",
        help="build the canonical daily cross-section v1 package",
    )
    standard.add_argument("--config-path", required=True)
    standard.add_argument("--output-dir", required=True)
    inspect = commands.add_parser("inspect", help="validate and inspect a built package")
    inspect.add_argument("path")
    args = parser.parse_args()
    if args.command == "build":
        print(build_dataset(args.spec))
        return
    if args.command == "build-standard":
        print(build_standard_dataset(args.config_path, args.output_dir))
        return
    package = open_dataset(args.path)
    print(json.dumps({
        "dataset_id": package.dataset_id,
        "default_view": package.default_view,
        "available_frames": package.available_frames,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
