import pytest
import sqlalchemy


from sqlalchemy_fsm import FSMField, transition, can_proceed, is_current
from sqlalchemy_fsm.exc import SetupError, PreconditionError, InvalidSourceStateError

from conftest import Base


def val_eq_condition(expected_value):
    def bound_val_eq_condition(self, instance, actual_value):
        return expected_value == actual_value
    return bound_val_eq_condition

def val_contains_condition(expected_values):
    def bound_val_contains_condition(self, instance, actual_value):
        return actual_value in expected_values
    return bound_val_contains_condition

def three_argument_condition(expected1, expected2, expected3):
    def bound_three_argument_condition(self, instance, arg1, arg2, arg3):
        return (arg1, arg2, arg3) == (expected1, expected2, expected3)
    return bound_three_argument_condition   

class MultiSourceBlogPost(Base):

    __tablename__ = 'MultiSourceBlogPost'
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key = True)
    state = sqlalchemy.Column(FSMField)
    side_effect = sqlalchemy.Column(sqlalchemy.String)

    def __init__(self, *args, **kwargs):
        self.state = 'new'
        self.side_effect = 'default'
        super(MultiSourceBlogPost, self).__init__(*args, **kwargs)

    @transition(source='new', target='hidden')
    def hide(self):
        self.side_effect = "did_hide"

    @transition(source='*', target='deleted')
    def delete(self):
        self.side_effect = "deleted"

    @transition(target='published', conditions=[
        val_contains_condition([1,2])
    ])
    class publish(object):

        @transition(source='new', conditions=[
            val_eq_condition(1)
        ])
        def do_one(self, instance, value):
            instance.side_effect = "did_one"

        @transition(source='new', conditions=[
            val_contains_condition([2, 42])
        ])
        def do_two(self, instance, value):
            instance.side_effect = "did_two"

        @transition(source='hidden')
        def do_unhide(self, instance, value):
            instance.side_effect = "did_unhide: {}".format(value)

        @transition(source='published')
        def do_publish_loop(self, instance, value):
            instance.side_effect = "do_publish_loop: {}".format(value)

    @transition(target='published', source=['new', 'something'])
    class noPreFilterPublish(object):

        @transition(source='*', conditions=[
            three_argument_condition(1, 2, 3)
        ])
        def do_three_arg_mk1(self, instance, val1, val2, val3):
            instance.side_effect = "did_three_arg_mk1::{}".format([val1, val2, val3])

        @transition(source='new', conditions=[
            three_argument_condition('str', -1, 42)
        ])
        def do_three_arg_mk2(self, instance, val1, val2, val3):
            instance.side_effect = "did_three_arg_mk2::{}".format([val1, val2, val3])


class TestMultiSourceBlogPost(object):

    @pytest.fixture
    def model(self):
        return MultiSourceBlogPost()

    def test_transition_one(self, model):
        assert can_proceed(model.publish, 1)

        model.publish(1)
        assert model.state == 'published'
        assert model.side_effect == 'did_one'

    def test_transition_two(self, model):
        assert can_proceed(model.publish, 2)

        model.publish(2)
        assert model.state == 'published'
        assert model.side_effect == 'did_two'

    def test_three_arg_transition_mk1(self, model):
        assert can_proceed(model.noPreFilterPublish, 1, 2, 3)
        model.noPreFilterPublish(1, 2, 3)
        assert model.state == 'published'
        assert model.side_effect == 'did_three_arg_mk1::[1, 2, 3]'

    def test_three_arg_transition_mk2(self, model):
        assert can_proceed(model.noPreFilterPublish, 'str', -1, 42)
        model.noPreFilterPublish('str', -1, 42)
        assert model.state == 'published'
        assert model.side_effect == "did_three_arg_mk2::['str', -1, 42]"

    def unable_to_proceed_with_invalid_kwargs(self, model):
        assert not can_proceed(model.noPreFilterPublish, 'str', -1, tomato='potato')

    def test_transition_two_incorrect_arg(self, model):
        # Transition should be rejected because of top-level `val_contains_condition([1,2])` constraint
        with pytest.raises(PreconditionError):
            model.publish(42)
        assert model.state == 'new'
        assert model.side_effect == 'default'

        # Verify that the exception can still be avoided with can_proceed() call
        assert not can_proceed(model.publish, 42)
        assert not can_proceed(model.publish, 4242)

    def test_hide(self, model):
        model.hide()
        assert model.state == 'hidden'
        assert model.side_effect == 'did_hide'

        model.publish(2)
        assert model.state == 'published'
        assert model.side_effect == 'did_unhide: 2'

    def test_publish_loop(self, model):
        model.publish(1)
        assert model.state == 'published'
        assert model.side_effect == 'did_one'

        for arg in (1, 2, 1, 1, 2):
            model.publish(arg)
            assert model.state == 'published'
            assert model.side_effect == 'do_publish_loop: {}'.format(arg)

    def test_delete_new(self, model):
        model.delete()
        assert model.state == 'deleted'

        # Can not switch from deleted to published
        assert not can_proceed(model.publish, 2)
        with pytest.raises(InvalidSourceStateError):
            model.publish(2)
        assert model.state == 'deleted'