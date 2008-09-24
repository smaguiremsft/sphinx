# -*- coding: utf-8 -*-
"""
    sphinx.search
    ~~~~~~~~~~~~~

    Create a search index for offline search.

    :copyright: 2007-2008 by Armin Ronacher.
    :license: BSD.
"""
import re
import cPickle as pickle
from cStringIO import StringIO

from docutils.nodes import Text, NodeVisitor

from sphinx.util.stemmer import PorterStemmer
from sphinx.util import json


word_re = re.compile(r'\w+(?u)')


class _JavaScriptIndex(object):
    """
    The search index as javascript file that calls a function
    on the documentation search object to register the index.
    This serializing system does not support chaining because
    simplejson (which it depends on) doesn't support it either.
    """

    PREFIX = 'Search.setIndex('
    SUFFIX = ')'

    def dumps(self, data):
        return self.PREFIX + json.dumps(data, separators=(',', ':')) \
               + self.SUFFIX

    def loads(self, s):
        data = s[len(self.PREFIX):-len(self.SUFFIX)]
        if not data or not s.startswith(self.PREFIX) or not \
           s.endswith(self.SUFFIX):
            raise ValueError('invalid data')
        return json.loads(data)

    def dump(self, data, f):
        f.write(self.dumps(data))

    def load(self, f):
        return self.loads(f.read())


js_index = _JavaScriptIndex()


class Stemmer(PorterStemmer):
    """
    All those porter stemmer implementations look hideous.
    make at least the stem method nicer.
    """

    def stem(self, word):
        word = word.lower()
        return PorterStemmer.stem(self, word, 0, len(word) - 1)


class WordCollector(NodeVisitor):
    """
    A special visitor that collects words for the `IndexBuilder`.
    """

    def __init__(self, document):
        NodeVisitor.__init__(self, document)
        self.found_words = []

    def dispatch_visit(self, node):
        if node.__class__ is Text:
            self.found_words.extend(word_re.findall(node.astext()))


class IndexBuilder(object):
    """
    Helper class that creates a searchindex based on the doctrees
    passed to the `feed` method.
    """
    formats = {
        'json':     json,
        'pickle':   pickle
    }

    def __init__(self, env):
        self.env = env
        self._stemmer = Stemmer()
        # filename -> title
        self._titles = {}
        # stemmed word -> set(filenames)
        self._mapping = {}
        # desctypes -> index
        self._desctypes = {'module': 0}

    def load(self, stream, format):
        """Reconstruct from frozen data."""
        if isinstance(format, basestring):
            format = self.formats[format]
        frozen = format.load(stream)
        # if an old index is present, we treat it as not existing.
        if not isinstance(frozen, dict):
            raise ValueError('old format')
        index2fn = frozen['filenames']
        self._titles = dict(zip(index2fn, frozen['titles']))
        self._mapping = dict((k, set(index2fn[i] for i in v))
                             for (k, v) in frozen['terms'].iteritems())
        # no need to load keywords/desctypes

    def dump(self, stream, format):
        """Dump the frozen index to a stream."""
        if isinstance(format, basestring):
            format = self.formats[format]
        format.dump(self.freeze(), stream)

    def get_keyword_map(self):
        """Return a dict of all keywords."""
        rv = {}
        dt = self._desctypes
        for kw, (ref, _, _, _) in self.env.modules.iteritems():
            rv[kw] = (ref, 0, 'module-' + kw)
        for kw, (ref, ref_type) in self.env.descrefs.iteritems():
            try:
                i = dt[ref_type]
            except KeyError:
                i = len(dt)
                dt[ref_type] = i
            rv[kw] = (ref, i, kw)
        return rv

    def freeze(self):
        """Create a usable data structure for serializing."""
        filenames = self._titles.keys()
        titles = self._titles.values()
        fn2index = dict((f, i) for (i, f) in enumerate(filenames))
        return dict(
            filenames=filenames,
            titles=titles,
            terms=dict((k, [fn2index[fn] for fn in v])
                       for (k, v) in self._mapping.iteritems()),
            keywords=dict((k, (fn2index[v[0]],) + v[1:]) for k, v in
                          self.get_keyword_map().iteritems()),
            desctypes=dict((v, k) for (k, v) in self._desctypes.items()),
        )

    def prune(self, filenames):
        """Remove data for all filenames not in the list."""
        new_titles = {}
        for filename in filenames:
            if filename in self._titles:
                new_titles[filename] = self._titles[filename]
        self._titles = new_titles
        for wordnames in self._mapping.itervalues():
            wordnames.intersection_update(filenames)

    def feed(self, filename, title, doctree):
        """Feed a doctree to the index."""
        self._titles[filename] = title

        visitor = WordCollector(doctree)
        doctree.walk(visitor)

        def add_term(word, prefix=''):
            word = self._stemmer.stem(word)
            self._mapping.setdefault(prefix + word, set()).add(filename)

        for word in word_re.findall(title):
            add_term(word)

        for word in visitor.found_words:
            add_term(word)
