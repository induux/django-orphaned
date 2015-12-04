from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from django_orphaned.app_settings import ORPHANED_APPS_MEDIABASE_DIRS
from itertools import chain
from optparse import make_option
from django.conf import settings

import os
import shutil


# traverse root folder and store all files and empty directories
def should_skip(dir, skip):
    for skip_dir in skip:
        if dir.startswith(skip_dir):
            return True
    return False


class Command(BaseCommand):
    help = "Delete all orphaned files"
    base_options = (
        make_option('--info', action='store_true', dest='info', default=False,
                    help='If provided, the files will not be deleted.'),
    )
    option_list = BaseCommand.option_list + base_options

    def _get_needed_files(self, app):
        """
        collects all needed files for an app. goes through every field of each
        model and detects FileFields and ImageFields
        """
        needed_files = []
        for model in ContentType.objects.filter(app_label=app):
            mc = model.model_class()
            if mc is None:
                continue
            fields = []
            for field in mc._meta.fields:
                if (field.get_internal_type() == 'FileField' or field.get_internal_type() == 'ImageField'):
                    fields.append(field.name)

            # we have found a model with FileFields
            if len(fields) > 0:
                files = mc.objects.all().values_list(*fields)
                needed_files.extend([os.path.join(settings.MEDIA_ROOT, file) for file in filter(None, chain.from_iterable(files))])

        return needed_files

    def _get_media_files(self, app_root, skip_roots, exclude_files):
        """
        collects all media files and empty directories for a root. respects
        the global 'skip' and 'exclude' rules provided by the app settings.
        """
        all_files = []
        possible_empty_dirs = []

        for root, dirs, files in os.walk(app_root):
            if len(files) > 0:
                for basename in files:
                    if basename not in exclude_files:
                        all_files.append(os.path.join(root, basename))
            elif not os.path.samefile(root, app_root):
                possible_empty_dirs.append(root)

        # ignore empty dirs with subdirs + files
        empty_dirs = []
        for ed in possible_empty_dirs:
            dont_delete = False
            for files in all_files:
                try:
                    if files.index(ed) == 0:
                        dont_delete = True
                except ValueError:
                    pass
            for skip_dir in skip_roots:
                try:
                    if (skip_dir.index(ed) == 0):
                        dont_delete = True
                except ValueError:
                    pass
            if not dont_delete:
                empty_dirs.append(ed)

        return all_files, empty_dirs

    def handle(self, **options):
        """
        goes through ever app given in the settings. if option 'info' is given,
        nothing would be deleted.
        """
        self.only_info = options.get('info')

        all_files = []
        needed_files = []
        empty_dirs = []
        total_freed_bytes = 0
        total_freed = '0'
        MEDIA_ROOTS = []
        SKIP_ROOTS = []
        EXCLUDE_FILES = []

        # collect media roots and create all_files
        for app in ORPHANED_APPS_MEDIABASE_DIRS.keys():
            if 'root' in ORPHANED_APPS_MEDIABASE_DIRS[app]:
                # process each root of the app
                app_roots = ORPHANED_APPS_MEDIABASE_DIRS[app]['root']
                skip_roots = ORPHANED_APPS_MEDIABASE_DIRS[app].get('skip', ())
                exclude_files = ORPHANED_APPS_MEDIABASE_DIRS[app].get('exclude', ())

                if isinstance(app_roots, basestring):  # backwards compatibility
                    app_roots = [app_roots]
                    MEDIA_ROOTS.extend(app_roots)

                for root in skip_roots:
                    SKIP_ROOTS.extend(root)

                for f in exclude_files:
                    EXCLUDE_FILES.extend(f)

        MEDIA_ROOTS = list(set(MEDIA_ROOTS))
        SKIP_ROOTS = list(set(SKIP_ROOTS))
        EXCLUDE_FILES = list(set(EXCLUDE_FILES))

        if self.only_info:
            print '====ROOTS===='
            print '-->MEDIA<--'
            for path in MEDIA_ROOTS:
                print ' -  {}'.format(path)
            print '-->SKIP<--'
            for path in SKIP_ROOTS:
                print ' -  {}'.format(path)
            print '-->EXCLUDE FILES<--'
            for f in EXCLUDE_FILES:
                print ' -  {}'.format(f)
            print '===================\n'
            print 'starting...'

        for root in MEDIA_ROOTS:
            if self.only_info:
                print '-> {}'.format(root)
            a, e = self._get_media_files(root, SKIP_ROOTS, EXCLUDE_FILES)
            if a:
                a = list(set(a))
            if e:
                e = list(set(e))
            if self.only_info:
                print 'got media files for {}'.format(root)

            all_files.extend(a)
            if all_files:
                all_files = list(set(all_files))
            if self.only_info:
                print 'all_files extended'

            empty_dirs.extend(e)
            if empty_dirs:
                empty_dirs = list(set(empty_dirs))
            if self.only_info:
                print 'empty_dirs extended'

        # distinguish needed_files
        for app in ORPHANED_APPS_MEDIABASE_DIRS.keys():
            if 'root' in ORPHANED_APPS_MEDIABASE_DIRS[app]:
                if self.only_info:
                    print '-' * 10
                    print 'inspecting {}'.format(app)
                    print '-' * 10

                needed_files.extend(self._get_needed_files(app))
                if needed_files:
                    needed_files = list(set(needed_files))
                if self.only_info:
                    print 'needed_files extended for {}'.format(app)

        # select deleted files (delete_files = all_files - needed_files)
        delete_files = sorted(set(all_files).difference(needed_files))
        empty_dirs = sorted(set(empty_dirs))  # remove possible duplicates

        # only show
        if self.only_info:
            print '=' * 10
            print 'total Files: {}'.format(len(all_files))
            print 'needed Files: {}'.format(len(needed_files))
            print '=' * 10
            # to be freed
            for df in delete_files:
                total_freed_bytes += os.path.getsize(df)
            total_freed = "%0.1f MB" % (total_freed_bytes / (1024 * 1024.0))

            if len(empty_dirs) > 0:
                print "\r\nFollowing empty dirs will be removed:\r\n"
                for file in empty_dirs:
                    print " ", file

            if len(delete_files) > 0:
                print "\r\nFollowing files will be deleted:\r\n"
                for file in delete_files:
                    print " ", file
                print "\r\nTotally %s files will be deleted, and "\
                    "totally %s will be freed.\r\n" % (len(delete_files), total_freed)
            else:
                print "No files to delete!"

        # otherwise delete
        else:
            for file in delete_files:
                os.remove(file)
            for dirs in empty_dirs:
                shutil.rmtree(dirs, ignore_errors=True)
