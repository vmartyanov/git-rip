"""Script to retrieve only file pathes from downloaded .git directory."""
import os
import sys

import git_rip

class FileROTransport(git_rip.BaseTransport):
    """Read-only file transport. No write/copy operations performed."""
    def __init__ (self, target: str):
        """Initialize transport."""
        self.target = target
        self.out_dir = target

        #does target exists?
        if not os.path.exists(target):
            raise git_rip.TransportException(f"{target} doesn't exists!")
        #is it a dir?
        if not os.path.isdir(target):
            raise git_rip.TransportException(f"{target} is not a rirectory!")

    def retrieve_file(self, relative_path: str) -> bool:
        """Always return False, because we don't retrieve anything."""
        return False


def main() -> None:
    """Main function."""
    transport = FileROTransport(sys.argv[1])
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
        try:
            print (path)
        except UnicodeEncodeError:
            pass


if __name__ == "__main__":
    main()
