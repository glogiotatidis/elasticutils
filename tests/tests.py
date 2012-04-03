"""
Run me using nose!

Also run elastic search on the default ports locally.
"""
from unittest import TestCase

from elasticutils import F, S, get_es
from nose.tools import eq_, assert_raises
import pyes.exceptions


class Meta(object):
    def __init__(self, db_table):
        self.db_table = db_table


class Manager(object):
    def filter(self, id__in=None):
        return [m for m in model_cache if m.id in id__in]

model_cache = []


class FakeModel(object):
    _meta = Meta('fake')
    objects = Manager()

    def __init__(self, **kw):
        for key in kw:
            setattr(self, key, kw[key])
        model_cache.append(self)


class QueryTest(TestCase):

    @classmethod
    def setup_class(cls):
        es = get_es()
        try:
            es.delete_index_if_exists('test')
        except pyes.exceptions.IndexMissingException:
            # No clue why we have to catch this---would have thought
            # it was handled by delete_index_if_exists.
            pass
        data1 = FakeModel(id=1, foo='bar', tag='awesome', width='2')
        data2 = FakeModel(id=2, foo='barf', tag='boring', width='7')
        data3 = FakeModel(id=3, foo='car', tag='awesome', width='5')
        data4 = FakeModel(id=4, foo='duck', tag='boat', width='11')
        data5 = FakeModel(id=5, foo='train car', tag='awesome', width='7')

        for data in (data1, data2, data3, data4, data5):
            es.index(data.__dict__, 'test', FakeModel._meta.db_table,
                    bulk=True, id=data.id)
        es.refresh()

    def test_q(self):
        eq_(len(S(FakeModel).query(foo='bar')), 1)
        eq_(len(S(FakeModel).query(foo='car')), 2)

    def test_q_all(self):
        eq_(len(S(FakeModel)), 5)

    def test_filter(self):
        eq_(len(S(FakeModel).filter(tag='awesome')), 3)
        eq_(len(S(FakeModel).filter(F(tag='awesome'))), 3)

    def test_filter_and(self):
        eq_(len(S(FakeModel).filter(tag='awesome', foo='bar')), 1)
        eq_(len(S(FakeModel).filter(tag='awesome').filter(foo='bar')), 1)
        eq_(len(S(FakeModel).filter(F(tag='awesome') & F(foo='bar'))), 1)

    def test_filter_or(self):
        eq_(len(S(FakeModel).filter(F(tag='awesome') | F(tag='boat'))), 4)

    def test_filter_or_3(self):
        eq_(len(S(FakeModel).filter(F(tag='awesome') | F(tag='boat') |
                                    F(tag='boring'))), 5)
        eq_(len(S(FakeModel).filter(or_={'foo': 'bar', 'or_': {'tag': 'boat',
                                    'width': '5'}})), 3)

    def test_filter_complicated(self):
        eq_(len(S(FakeModel).filter(F(tag='awesome', foo='bar') |
            F(tag='boring'))), 2)

    def test_filter_not(self):
        eq_(len(S(FakeModel).filter(~F(tag='awesome'))), 2)
        eq_(len(S(FakeModel).filter(~(F(tag='boring') | F(tag='boat')))), 3)
        eq_(len(S(FakeModel).filter(~F(tag='boat')).filter(~F(foo='bar'))), 3)
        eq_(len(S(FakeModel).filter(~F(tag='boat', foo='barf'))), 5)

    def test_facet(self):
        qs = S(FakeModel).facet(tags={'terms': {'field': 'tag'}})
        tag_counts = dict((t['term'], t['count']) for t in qs.facets['tags'])

        eq_(tag_counts, dict(awesome=3, boring=1, boat=1))

    def test_order_by(self):
        res = S(FakeModel).filter(tag='awesome').order_by('-width')
        eq_([d.id for d in res], [5, 3, 1])

    def test_repr(self):
        res = S(FakeModel)[:2]
        list_ = list(res)

        eq_(repr(list_), repr(res))

    def test_result_metadata(self):
        """Test that metadata is on the results"""
        s = (S(FakeModel).query(foo__text='car')
                         .filter(id=5))
        result = list(s)[0]  # Get the only result.
        # This is a little goofy, but we don't want to test against
        # a specific score since that could break the test if you
        # used a different version of elasticsearch.
        assert result._score > 0

        eq_(result._type, 'fake')

    def _test_excerpt(self, method_name=None, *fields):
        """Test excerpting with some arbitrary result format.

        :arg method_name: The name of the method used to select the result
            format. Omit for object-style results.
        :arg fields: The arguments to pass to said method

        """
        s = (S(FakeModel).query(foo__text='car')
                         .filter(id=5)
                         .highlight('tag', 'foo'))
        if method_name:
            # Call values_dict() or values():
            s = getattr(s, method_name)(*fields)
        result = list(s)[0]  # Get the only result.
        # The highlit text from the foo field should be in index 1 of the
        # excerpts.
        eq_(result._highlighted['foo'], [u'train <em>car</em>'])

    def test_excerpt_on_object_results(self):
        """Make sure excerpting with object-style results works."""
        self._test_excerpt()

    def test_excerpt_on_dict_results(self):
        """Make sure excerpting with dict-style results works.

        Highlighting should work on all fields specified in the ``highlight()``
        call, not just the ones mentioned in the query or in ``values_dict()``.

        """
        self._test_excerpt('values_dict', 'foo')

    def test_excerpt_on_list_results(self):
        """Make sure excerpting with list-style results works.

        Highlighting should work on all fields specified in the ``highlight()``
        call, not just the ones mentioned in the query or in ``values_list()``.

        """
        self._test_excerpt('values', 'foo')

    @classmethod
    def teardown_class(cls):
        es = get_es()
        es.delete_index('test')


def test_weight_term():
    """Test that weights are properly applied to term queries."""
    eq_(S(FakeModel).weight(fld1=2)
                    .query(fld1='qux')
                    ._build_query(),
        {"query":
            {"term": {"fld1": {"value": "qux", "boost": 2}}},
         "fields":
            ["id"]})


def test_weight_text():
    """Test that weights are properly applied to text queries."""
    eq_(S(FakeModel).weight(fld2__text=7)
                    .query(fld2__text='qux')
                    ._build_query(),
        {"query":
            {"text": {"fld2": {"query": "qux", "boost": 7}}},
         "fields":
            ["id"]})


def test_weight_startswith():
    """Test that weights are properly applied to prefix queries."""
    eq_(S(FakeModel).query(fld4__startswith='qux')
                    .weight(fld4__startswith=3)
                    ._build_query(),
        {"query":
            {"prefix": {"fld4": {"value": "qux", "boost": 3}}},
         "fields":
            ["id"]})


def test_weight_multiple():
    """Test that multiple weights are properly applied."""
    eq_(S(FakeModel).query_fields('fld1', 'fld2__text')
                    .weight(fld1=2, fld2__text=7)
                    .query('qux')
                    ._build_query(),
        {"query":
            {"bool":
                {"should":
                    [{"text": {"fld2": {"query": "qux", "boost": 7}}},
                     {"term": {"fld1": {"value": "qux", "boost": 2}}}]}},
         "fields":
            ["id"]})


def test_query_fields():
    """Make sure queries against a default set of fields works."""
    implicit = S(FakeModel).query_fields('fld1', 'fld2__text').query('boo')
    explicit = S(FakeModel).query(or_=dict(fld1='boo', fld2__text='boo'))
    eq_(implicit._build_query(), explicit._build_query())


def test_query_type_error():
    """``query()`` should throw a ``TypeError`` when called with neither or
    both args and kwargs."""
    assert_raises(TypeError, S(FakeModel).query)
    assert_raises(TypeError, S(FakeModel).query, 'hey', frob='yo')


def test_highlight_query():
    """Assert that a ``highlight()`` call produces the right query."""
    eq_(S(FakeModel).query(title__text='boof')
                    .highlight('color', 'smell',
                               before_match='<i>',
                               after_match='</i>')
                    ._build_query()['highlight'],
        {"fields": {"color": {},
                    "smell": {}},
         "pre_tags": ["<i>"],
         "post_tags": ["</i>"],
         'order': 'score'})


def test_values_dict_no_args():
    """Calling ``values_dict()`` with no args implicitly fetches all fields."""
    eq_(S(FakeModel).query(fld1=2)
                    .values_dict()
                    ._build_query(),
        {"query":
            {"term": {"fld1": 2}}})


def test_values_no_args():
    """Calling ``values()`` with no args fetches only ID."""
    eq_(S(FakeModel).query(fld1=2)
                    .values()
                    ._build_query(),
        {'query':
            {"term": {"fld1": 2}},
         'fields': ['id']})


def test_values_dict_id():
    """Calling ``values_dict('id')`` shouldn't return the ID field twice."""
    eq_(S(FakeModel).query(fld1=2)
                    .values_dict('id')
                    ._build_query(),
        {'query':
            {"term": {"fld1": 2}},
         'fields': ['id']})


def test_values_id():
    """Calling ``values('id')`` shouldn't return the ID field twice."""
    eq_(S(FakeModel).query(fld1=2)
                    .values('id')
                    ._build_query(),
        {'query':
            {"term": {"fld1": 2}},
         'fields': ['id']})


def test_values_dict_implicit_id():
    """Calling ``values_dict()`` always fetches ID."""
    eq_(S(FakeModel).query(fld1=2)
                    .values_dict('thing')
                    ._build_query(),
        {'query':
            {"term": {"fld1": 2}},
         'fields': ['thing', 'id']})


def test_values_implicit_id():
    """Calling ``values()`` always fetches ID."""
    eq_(S(FakeModel).query(fld1=2)
                    .values('thing')
                    ._build_query(),
        {'query':
            {"term": {"fld1": 2}},
         'fields': ['thing', 'id']})
