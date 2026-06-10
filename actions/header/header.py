import os
import datetime
import sys
import fnmatch

header_test = 'Released under a MIT (SEI)-style license'
header = 'Copyright ' + str(datetime.date.today().year) + ' Carnegie Mellon University. All Rights Reserved.\nReleased under a MIT (SEI)-style license. See LICENSE.md in the project root for license information.'

use_block_comments = False

if len(sys.argv) > 1:
    use_block_comments = sys.argv[1].lower() == 'true'


def load_ignore_patterns(path='.headerignore'):
    # Read gitignore-style exemption patterns from a .headerignore file in the
    # repo root. Missing file means no exemptions (original behavior).
    patterns = []
    if not os.path.isfile(path):
        return patterns
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            # skip blank lines and comments
            if not line or line.startswith('#'):
                continue
            patterns.append(line)
    return patterns


def is_ignored(rel_path, patterns):
    # Match a repo-relative path (forward-slash separated, no leading ./)
    # against the ignore patterns. Supports:
    #   - glob patterns (fnmatch), e.g. "*.md", ".agents/**"
    #   - directory prefixes, e.g. ".agents/" or ".agents" exempt the whole tree
    for pattern in patterns:
        # directory-prefix patterns: a trailing slash, or a bare dir name,
        # exempts everything beneath it
        dir_prefix = pattern.rstrip('/')
        if rel_path == dir_prefix or rel_path.startswith(dir_prefix + '/'):
            return True
        # glob match against the full relative path
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        # support "**" recursive globs, which fnmatch doesn't expand by default
        if '**' in pattern and fnmatch.fnmatch(rel_path, pattern.replace('**', '*')):
            return True
    return False


ignore_patterns = load_ignore_patterns()
if ignore_patterns:
    print('header ignore patterns:')
    for pattern in ignore_patterns:
        print('  ' + pattern)

print('header not in:')
# iterate over all files in directory
for root, dirs, files in os.walk("."):
    for file in files:
        # only care about files with extensions considered to be source code
        if file.endswith(('.cs', '.ts', '.js', '.css', '.php', '.xml', '.html', '.scss', '.py', '.go')):
            # normalize to a repo-relative, forward-slash path and skip exemptions
            rel_path = os.path.relpath(os.path.join(root, file), '.').replace(os.sep, '/')
            if is_ignored(rel_path, ignore_patterns):
                print('skipping (ignored): ' + rel_path)
                continue
            # open file & read it
            with open(os.path.join(root,file), 'r') as original: data = original.read()
            # check file for header
            if (data.find(header_test) == -1):
                print(file)
                comment_start = ''
                comment_end = ''
                # add header to file
                if file.endswith(('.cs', '.ts', '.js', '.css', '.go', '.scss', '.php')):
                    if use_block_comments:
                        # comment type /* __ */
                        comment_start = '/*'
                        comment_end = '*/'                         
                    else:
                        # comment type //
                        comment_start = '// '
                        comment_end = '\n'
                elif file.endswith(('.xml', '.html')):
                    if use_block_comments:
                        # comment type <!-- __ -->
                        comment_start = '<!--'
                        comment_end = '-->'                    
                    else:
                        # comment type <!-- __ -->
                        comment_start = '<!-- '
                        comment_end = ' -->\n'
                elif file.endswith('py'):
                    if use_block_comments:
                        # comment type """ ___ """
                        comment_start = '"""'
                        comment_end = '"""'                         
                    else:
                        # comment type #
                        comment_start = '# '
                        comment_end = '\n'

                if use_block_comments:
                    with open(os.path.join(root,file), 'w') as modified: modified.write(f'{comment_start}\n{header}\n{comment_end}\n\n' + data)
                else:
                    with open(os.path.join(root,file), 'w') as modified: 
                        for header_line in header.split('\n'):
                            modified.write(f'{comment_start}{header_line}{comment_end}')   
                        modified.write('\n' + data)