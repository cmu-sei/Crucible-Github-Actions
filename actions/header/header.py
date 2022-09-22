import os
import datetime
import sys

header_test = 'Released under a MIT (SEI)-style license'
header = 'Copyright ' + str(datetime.date.today().year) + ' Carnegie Mellon University. All Rights Reserved.\nReleased under a MIT (SEI)-style license. See LICENSE.md in the project root for license information.'

use_block_comments = False

if len(sys.argv) > 1:
    use_block_comments = sys.argv[1].lower() == 'true'

print('header not in:')
# iterate over all files in directory 
for root, dirs, files in os.walk("."):
    for file in files:
        # only care about files with extensions considered to be source code
        if file.endswith(('.cs', '.ts', '.js', '.css', '.php', '.xml', '.html', '.scss', '.py', '.go')):
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