from tinydb_serialization.serializers import DateTimeSerializer
from tinydb_serialization import SerializationMiddleware
from tinydb import JSONStorage, TinyDB, where
from tinydb.table import Table, Document
from typing import Dict, List, Optional
from abc import ABC, abstractmethod
import logging


_logger = logging.getLogger(__name__)
_serialization = SerializationMiddleware(JSONStorage)
_database = TinyDB('database.json', storage=_serialization, indent=4)
_models = {}


def register_model(cls):
    global _models
    _logger.info('Registering model %s', cls.__name__)
    _models[cls.__name__] = cls
    return cls


class FieldUniqueError(Exception): ...
class FieldRequiredError(Exception): ...
class FieldValidationError(Exception): ...   
class FieldGroupUniqueError(Exception): ...
class DanglingReferenceError(Exception): ...
class UnregisteredModelError(Exception): ...


class Field:
    def __init__(self, type, **kwargs):
        self.type = type
        self.required = kwargs.pop('required', False)
        self.default = kwargs.pop('default', lambda: self.type())

        def default_validator(field):
            if not isinstance(field, self.type):
                message = f'{repr(field)} is not an instance of {self.type}'
                raise FieldValidationError(message)

        self.validator = kwargs.pop('validator', default_validator)
        self.unique = kwargs.pop('unique', False)
        self.unique_with = kwargs.pop('unique_with', [])


# Like `@property` but static.
class classproperty(property):
    def __get__(self, _, objtype=None):
        return super(classproperty, self).__get__(objtype)

    def __set__(self, obj, value):
        super(classproperty, self).__set__(type(obj), value)

    def __delete__(self, obj):
        super(classproperty, self).__delete__(type(obj))


class Fetchable(ABC):
    @abstractmethod
    def fetch(self):
        raise NotImplementedError()


class LazyModel(Fetchable):
    def __init__(self, model_cls, doc_id):
        self.model_cls = model_cls
        self.doc_id = doc_id
    
    def fetch(self) -> 'Model':
        _logger.info('Evaluating %s/%s', self.model_cls, self.doc_id)
        document = self.model_cls.get(doc_id=self.doc_id)
        
        if document is None:
            table_name = self.model_cls._get_table().name
            message = f'Table {repr(table_name)} has no id {self.doc_id}'
            raise DanglingReferenceError(message)
        
        return document


class Model(Fetchable):
    TABLE_PREFIX = 'TinyEngine/'

    def __init__(self, doc_id=None, **kwargs):
        self.doc_id = doc_id
        for key, value in kwargs.items():
            self.__dict__[key] = value

    def _get_fields(self) -> Dict[str, Field]:
        return {
            key: value
            for key, value in self.__class__.__dict__.items()
            if isinstance(value, Field)
        }

    @classmethod
    def _get_table(cls) -> Table:
        global _database
        table_name = f'{Model.TABLE_PREFIX}{cls.__name__}'
        return _database.table(table_name)

    def _handle_unique_collision(self, document):
        _logger.warning('Collision with %s in table %s, overwriting',
            document, self.__class__._get_table().name)
        self.doc_id = document.doc_id

    def _validate(self):
        unique_group = []

        for name, field in self._get_fields().items():
            if name not in self.__dict__:
                if field.required:
                    message = f'{repr(name)} is a required field'
                    raise FieldRequiredError(message)
                
                value = field.default()
                self.__dict__[name] = value
            
            value = self.__dict__[name]
            field.validator(value)

            if field.unique:
                query = where(name) == value
                document = self.get(query)
                if document is not None and document.doc_id != self.doc_id:
                    self._handle_unique_collision(document)

                    #     x = f'{repr(self)}.{name} is not unique: {value}'
                    #     raise FieldUniqueError(x) 
            
            if field.unique_with:
                unique_group = [name] + field.unique_with
        
        if unique_group:
            
            # Build query from names of fields.
            query = None
            for name in unique_group:
                value = self.__dict__[name]

                if query is None:
                    query = where(name) == value
                else:
                    query = query & (where(name) == value)
            
            document = self.get(query)
            if document is not None and document.doc_id != self.doc_id:
                self._handle_unique_collision(document)

                #     x = f'{repr(self)} has non-unique fields: {unique_group}'
                #     raise FieldGroupUniqueError(x)

    @classmethod
    def _evaluate_deep(cls, obj):
        # TODO: This is an experimental feature, do not rely on this.
        
        # Evaluate non-nested models.
        for key, value in obj.__dict__.items():
            if isinstance(value, LazyModel):
                obj.__dict__[key] = value.get()
                cls._evaluate_deep(obj.__dict__[key])
        
        def _enumerate(obj):
            # Object is a dictionary, list, or tuple.
            if isinstance(obj, dict):
                return obj.items()
            else: # A list or tuple.
                return enumerate(obj)

        # Evaluate models that are nested in dictionaries or lists.
        for key, value in obj.__dict__.items():
            if isinstance(value, (dict, list, tuple)):
                for index, value_2 in _enumerate(value):
                    if isinstance(value_2, LazyModel):
                        value[index] = value_2.get()
                        cls._evaluate_deep(value[index])

    # ...

    def save(self) -> 'Model':
        self._validate()

        table = self.__class__._get_table()
        doc_id = self.doc_id if self.doc_id is not None else \
            table._get_next_id()
        
        keys = self.__dict__.keys() - {'doc_id'}
        document = Document({
            key: self.__dict__[key]
            for key in keys
        }, doc_id=doc_id)

        self.doc_id = table.upsert(document)[0]
        return self

    def delete(self):
        if self.doc_id is None:
            raise ValueError('Cannot delete non-existent document')
        
        table = self.__class__._get_table()
        table.remove(doc_ids=[self.doc_id])

    @classmethod
    def search(cls, *args, **kwargs) -> List['Model']:
        results = cls._get_table().search(*args, **kwargs)
        return [
            # The first sets the `doc_id` field.
            # The second sets the rest.
            cls(**result.__dict__, **result)
            for result in results
        ]
    
    @classmethod
    def get(cls, *args, **kwargs) -> Optional['Model']:
        result = cls._get_table().get(*args, **kwargs)
        return None if result is None else \
            cls(**result.__dict__, **result)

    @classproperty
    def objects(cls):
        for document in cls._get_table():
            yield cls(**document.__dict__, **document)
    
    def fetch(self):
        return self


    # ...

    def __str__(self) -> str:
        return str(self.__dict__)

class ModelSerializer:
    OBJ_CLASS = Model

    def encode(self, x):
        if x.doc_id is None:
            message = f'{str(x)} is not in the database'
            raise DanglingReferenceError(message)
        
        return x.__class__.__name__ + '/' + str(x.doc_id)

    def decode(self, s):
        cls_name, doc_id = s.split('/')

        # Cannot de-serialize if we do not have a handle to the class.
        if cls_name not in _models:
            raise UnregisteredModelError(cls_name)

        return LazyModel(_models[cls_name], int(doc_id))

# Almost exactly the same as `ModelSerializer`.
class LazyModelSerializer:
    OBJ_CLASS = LazyModel

    def encode(self, x):
        return x.model_cls.__name__ + '/' + str(x.doc_id)

    def decode(self, s):
        cls_name, doc_id = s.split('/')
        
        # Cannot de-serialize if we do not have a handle to the class.
        if cls_name not in _models:
            raise UnregisteredModelError(cls_name)
        
        return LazyModel(_models[cls_name], int(doc_id))


_serialization.register_serializer(ModelSerializer(), 'TinyModel')
_serialization.register_serializer(DateTimeSerializer(), 'TinyDate')
_serialization.register_serializer(LazyModelSerializer(), 'TinyLazy')
