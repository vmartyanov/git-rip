"""Script to retrieve only file pathes from downloaded .git directory."""
import os
import sys

import git_rip

def main() -> None:
    """Main function."""
    transport = git_rip.FileROTransport(sys.argv[1])
    tree = git_rip.TreeBuilder()

    #Get objects from logs/HEAD and process them
    objects = git_rip.parse_logs_head(transport.get_content("logs/HEAD"))
    processed = git_rip.objects_loop(transport, tree, objects)

    #Get objects from index and process them
    objects = git_rip.parse_index(transport.get_content("index"), tree)
    objects = objects - processed
    git_rip.objects_loop(transport, tree, objects)

    #drop names_from_git
    items = tree.get_tree(None)
    paths = set()
    for path, _ in items:
        paths.add(path)

    for path in paths:
        try:
            print (path)
        except UnicodeEncodeError:
            pass


if __name__ == "__main__":
    main()
