# -*- coding: utf-8 -*-
#
# Copyright (c), 2016, SISSA (International School for Advanced Studies).
# All rights reserved.
# This file is distributed under the terms of the MIT License.
# See the file 'LICENSE' in the root directory of the present
# distribution, or http://opensource.org/licenses/MIT.
#
# @author Davide Brunato <brunato@sissa.it>
#
"""
This module contains the exception classes of the 'xmlschema' package.
"""
try:
    # Python 3 specific imports
    from urllib.error import URLError
except ImportError:
    # Python 2 fallback
    # noinspection PyCompatibility
    from urllib2 import URLError

from .core import PY3, etree_tostring, etree_iselement


class XMLSchemaException(Exception):
    """The base exception that let you catch all the errors generated by the library."""
    pass


class XMLSchemaOSError(XMLSchemaException, OSError):
    pass


class XMLSchemaAttributeError(XMLSchemaException, AttributeError):
    pass


class XMLSchemaTypeError(XMLSchemaException, TypeError):
    pass


class XMLSchemaValueError(XMLSchemaException, ValueError):
    pass


class XMLSchemaSyntaxError(XMLSchemaException, SyntaxError):
    pass


class XMLSchemaKeyError(XMLSchemaException, KeyError):
    pass


class XMLSchemaURLError(XMLSchemaException, URLError):
    pass


class XMLSchemaNotBuiltError(XMLSchemaException, RuntimeError):
    """Raised when a not built XSD component or schema is used."""
    pass


class XMLSchemaParseError(XMLSchemaException, ValueError):
    """Raised when an error is found when parsing an XML Schema component."""

    def __init__(self, message, component=None, elem=None):
        self.message = message or u''
        self.component = component
        self.elem = elem or getattr(component, 'elem', None)

    def __str__(self):
        # noinspection PyCompatibility
        return unicode(self).encode("utf-8")

    def __unicode__(self):
        if etree_iselement(self.elem):
            return u''.join([
                self.message,
                u"\n\n  %s\n" % etree_tostring(self.elem, max_lines=20)
            ])
        else:
            return self.message

    if PY3:
        __str__ = __unicode__


class XMLSchemaRegexError(XMLSchemaParseError):
    """Raised when an error is found when parsing an XML Schema regular expression."""
    pass


class XMLSchemaXPathError(XMLSchemaParseError):
    """Raised when an error is found when parsing an XPath expression."""
    pass


class XMLSchemaValidationError(XMLSchemaException, ValueError):
    """Raised when the XML data is not validated with the XSD component or schema."""

    def __init__(self, validator, obj, reason=None, schema_elem=None, elem=None):
        self.validator = validator
        self.obj = obj
        self.reason = reason
        self.schema_elem = schema_elem or getattr(validator, 'elem', None)
        self.elem = elem or obj if etree_iselement(obj) else None
        self.message = None

    def __str__(self):
        # noinspection PyCompatibility
        return unicode(self).encode("utf-8")

    def __unicode__(self):
        return u''.join([
            self.message or u"failed validating %r with %r.\n" % (self.obj, self.validator),
            u'\nReason: %s\n' % self.reason if self.reason is not None else '',
            u"\nSchema:\n\n  %s\n" % etree_tostring(
                self.schema_elem, max_lines=20
            ) if self.schema_elem is not None else '',
            u"\nInstance:\n\n  %s\n" % etree_tostring(
                self.elem, max_lines=20
            ) if self.elem is not None else ''
        ])

    if PY3:
        __str__ = __unicode__


class XMLSchemaDecodeError(XMLSchemaValidationError):
    """Raised when an XML data string is not decodable to a Python object."""

    def __init__(self, validator, obj, decoder, reason=None):
        super(XMLSchemaDecodeError, self).__init__(validator, obj, reason)
        self.decoder = decoder
        self.message = u"failed decoding %r with %r.\n" % (obj, validator)


class XMLSchemaEncodeError(XMLSchemaValidationError):
    """Raised when an object is not encodable to an XML data string."""

    def __init__(self, validator, obj, encoder, reason=None):
        super(XMLSchemaEncodeError, self).__init__(validator, obj, reason)
        self.encoder = encoder
        self.message = u"failed encoding %r with %r.\n" % (obj, validator)
