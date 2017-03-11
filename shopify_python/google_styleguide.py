import re
import typing  # pylint: disable=unused-import

import astroid  # pylint: disable=unused-import
import shopify_python.ast
import six

from pylint import checkers
from pylint import interfaces
from pylint import lint  # pylint: disable=unused-import
from pylint import utils


def register_checkers(linter):  # type: (lint.PyLinter) -> None
    """Register checkers."""
    linter.register_checker(GoogleStyleGuideChecker(linter))


class GoogleStyleGuideChecker(checkers.BaseChecker):
    """
    Pylint checker for the Google Python Style Guide.

    See https://google.github.io/styleguide/pyguide.html

    Checks that can't be implemented include:
      - When capturing an exception, use as rather than a comma

    Checks that are already covered by Pylint include:
      - Never use catch-all 'except:' statements, or 'catch Exception' (bare-except, broad-except)
      - Do not use mutable objects as default values in the function or method definition (dangerous-default-value)
    """
    __implements__ = (interfaces.IAstroidChecker,)

    name = 'google-styleguide-checker'

    msgs = {
        'C2601': ('%(child)s is not a module or cannot be imported',
                  'import-modules-only',
                  'Only import packages or modules and ensure that they are installed.'),
        'C2602': ('%(module)s imported relatively',
                  'import-full-path',
                  'Import modules using their absolute names.'),
        'C2603': ('%(name)s declared at the module level (i.e. global)',
                  'global-variable',
                  'Avoid global variables in favor of class variables.'),
        'C2604': ('Raised two-argument exception',
                  'two-arg-exception',
                  "Use either raise Exception('message') or raise Exception."),
        'C2605': ('Raised deprecated string-exception',
                  'string-exception',
                  "Use either raise Exception('message') or raise Exception."),
        'C2606': ('Caught StandardError',
                  'catch-standard-error',
                  "Don't catch StandardError."),
        'C2607': ('Try body has %(found)i nodes',
                  'try-too-long',
                  "The larger the 'try' body size, the more likely that an unexpected exception will be raised."),
        'C2608': ('Except body has %(found)i nodes',
                  'except-too-long',
                  "The larger the 'except' body size, the more likely that an exception will be raised during "
                  "exception handling."),
        'C2609': ('Finally body has %(found)i nodes',
                  'finally-too-long',
                  "The larger the 'finally' body size, the more likely that an exception will be raised during "
                  "resource cleanup activities."),
    }

    options = (
        ('ignore-module-import-only', {
            'default': ('__future__',),
            'type': 'csv',
            'help': 'List of top-level module names separated by comma.'}),
        ('max-try-nodes', {
            'default': 25,
            'type': 'int',
            'help': 'Number of AST nodes permitted in a try-block'}),
        ('max-except-nodes', {
            'default': 23,
            'type': 'int',
            'help': 'Number of AST nodes permitted in an except-block'}),
        ('max-finally-nodes', {
            'default': 13,
            'type': 'int',
            'help': 'Number of AST nodes permitted in a finally-block'}),
    )

    def visit_assign(self, node):  # type: (astroid.Assign) -> None
        self.__avoid_global_variables(node)

    def visit_excepthandler(self, node):  # type: (astroid.ExceptHandler) -> None
        self.__dont_catch_standard_error(node)

    def visit_tryexcept(self, node):  # type: (astroid.TryExcept) -> None
        self.__minimize_code_in_try_except(node)

    def visit_tryfinally(self, node):  # type: (astroid.TryFinally) -> None
        self.__minimize_code_in_finally(node)

    def visit_importfrom(self, node):  # type: (astroid.ImportFrom) -> None
        self.__import_modules_only(node)
        self.__import_full_path_only(node)

    def visit_raise(self, node):  # type: (astroid.Raise) -> None
        self.__dont_use_archaic_raise_syntax(node)

    @staticmethod
    def __get_module_names(node):  # type: (astroid.ImportFrom) -> typing.Generator[str, None, None]
        for name in node.names:
            name, _ = name
            yield '.'.join((node.modname, name))  # Rearrange "from x import y" as "import x.y"

    def __import_modules_only(self, node):  # type: (astroid.ImportFrom) -> None
        """Use imports for packages and modules only."""
        matches_ignored_module = any((node.modname.startswith(module_name) for module_name in
                                      self.config.ignore_module_import_only))  # pylint: disable=no-member
        if not node.level and not matches_ignored_module:
            # Walk up the parents until we hit one that can import a module (e.g. a module)
            parent = node.parent
            while not hasattr(parent, 'import_module'):
                parent = parent.parent

            # Warn on each imported name (yi) in "from x import y1, y2, y3"
            for child_module in self.__get_module_names(node):
                args = {'child': child_module}
                try:
                    parent.import_module(child_module)
                except astroid.exceptions.AstroidBuildingException as building_exception:
                    if str(building_exception).startswith('Unable to load module'):
                        self.add_message('import-modules-only', node=node, args=args)
                    else:
                        raise

    def __import_full_path_only(self, node):  # type: (astroid.ImportFrom) -> None
        """Import each module using the full pathname location of the module."""
        if node.level:
            for child_module in self.__get_module_names(node):
                self.add_message('import-full-path', node=node, args={'module': child_module})

    def __avoid_global_variables(self, node):  # type: (astroid.Assign) -> None
        """Avoid global variables."""

        def check_assignment(node):
            if utils.get_global_option(self, 'class-rgx').match(node.name):
                return  # Type definitions are allowed if they assign to a class name

            if utils.get_global_option(self, 'const-rgx').match(node.name) or \
               re.match('^__[a-z]+__$', node.name):
                return  # Constants are allowed

            self.add_message('global-variable', node=node, args={'name': node.name})

        # Is this an assignment happening within a module? If so report on each assignment name
        # whether its in a tuple or not
        if isinstance(node.parent, astroid.Module):
            for target in node.targets:
                if hasattr(target, 'elts'):
                    for elt in target.elts:
                        check_assignment(elt)
                elif hasattr(target, 'name'):
                    check_assignment(target)

    def __dont_use_archaic_raise_syntax(self, node):  # type: (astroid.Raise) -> None
        """Don't use the two-argument form of raise or the string raise"""
        children = list(node.get_children())
        if len(children) > 1 and not isinstance(children[1], astroid.Name):
            self.add_message('two-arg-exception', node=node)
        elif len(children) == 1 and isinstance(children[0], six.string_types):
            self.add_message('string-exception', node=node)

    def __dont_catch_standard_error(self, node):  # type: (astroid.ExceptHandler) -> None
        """
        Never use catch-all 'except:' statements, or catch Exception or StandardError.

        Pylint already handles bare-except and broad-except (for Exception).
        """
        if hasattr(node.type, 'name') and node.type.name == 'StandardError':
            self.add_message('catch-standard-error', node=node)

    def __minimize_code_in_try_except(self, node):  # type: (astroid.TryExcept) -> None
        """Minimize the amount of code in a try/except block."""
        try_body_nodes = sum((shopify_python.ast.count_tree_size(child) for child in node.body))
        if try_body_nodes > self.config.max_try_nodes:  # pylint: disable=no-member
            self.add_message('try-too-long', node=node, args={'found': try_body_nodes})
        for handler in node.handlers:
            except_nodes = shopify_python.ast.count_tree_size(handler)
            if except_nodes > self.config.max_except_nodes:  # pylint: disable=no-member
                self.add_message('except-too-long', node=handler, args={'found': except_nodes})

    def __minimize_code_in_finally(self, node):  # type: (astroid.TryFinally) -> None
        """Minimize the amount of code in a finally block."""
        finally_body_nodes = sum((shopify_python.ast.count_tree_size(child) for child in node.finalbody))
        if finally_body_nodes > self.config.max_finally_nodes:  # pylint: disable=no-member
            self.add_message('finally-too-long', node=node, args={'found': finally_body_nodes})