# -*- coding: utf-8 -*-
#
# Copyright (c), 2016-2019, SISSA (International School for Advanced Studies).
# All rights reserved.
# This file is distributed under the terms of the MIT License.
# See the file 'LICENSE' in the root directory of the present
# distribution, or http://opensource.org/licenses/MIT.
#
# @author Davide Brunato <brunato@sissa.it>
#
"""
This module contains functions and classes for namespaces XSD declarations/definitions.
"""
from __future__ import unicode_literals
import re
import warnings
from collections import Counter

from ..exceptions import XMLSchemaKeyError, XMLSchemaTypeError, XMLSchemaValueError, XMLSchemaWarning
from ..namespaces import XSD_NAMESPACE
from ..qnames import XSD_INCLUDE, XSD_IMPORT, XSD_REDEFINE, XSD_OVERRIDE, XSD_NOTATION, XSD_ANY_TYPE, \
    XSD_SIMPLE_TYPE, XSD_COMPLEX_TYPE, XSD_GROUP, XSD_ATTRIBUTE, XSD_ATTRIBUTE_GROUP, XSD_ELEMENT
from ..helpers import get_qname, local_name
from ..namespaces import NamespaceResourcesMap

from . import XMLSchemaNotBuiltError, XMLSchemaModelError, XMLSchemaModelDepthError, XsdValidator, \
    XsdKeyref, XsdComponent, XsdAttribute, XsdSimpleType, XsdComplexType, XsdElement, XsdAttributeGroup, \
    XsdGroup, XsdNotation, XsdAssert
from .builtins import xsd_builtin_types_factory


def camel_case_split(s):
    """
    Split words of a camel case string
    """
    return re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)', s)


def iterchildren_by_tag(tag):
    """
    Defines a generator that produce all child elements that have a specific tag.
    """
    def iterfind_function(elem):
        for e in elem:
            if e.tag == tag:
                yield e
    iterfind_function.__name__ = str('iterfind_xsd_%ss' % '_'.join(camel_case_split(local_name(tag))).lower())
    return iterfind_function


iterchildren_xsd_import = iterchildren_by_tag(XSD_IMPORT)
iterchildren_xsd_include = iterchildren_by_tag(XSD_INCLUDE)
iterchildren_xsd_redefine = iterchildren_by_tag(XSD_REDEFINE)
iterchildren_xsd_override = iterchildren_by_tag(XSD_OVERRIDE)


#
# Defines the load functions for XML Schema structures
def create_load_function(filter_function):

    def load_xsd_globals(xsd_globals, schemas):
        redefinitions = []
        for schema in schemas:
            target_namespace = schema.target_namespace
            for elem in iterchildren_xsd_redefine(schema.root):
                location = elem.get('schemaLocation')
                if location is None:
                    continue
                for child in filter_function(elem):
                    qname = get_qname(target_namespace, child.attrib['name'])
                    redefinitions.append((qname, child, schema, schema.includes[location]))

            for elem in filter_function(schema.root):
                qname = get_qname(target_namespace, elem.attrib['name'])
                try:
                    xsd_globals[qname].append((elem, schema))
                except KeyError:
                    xsd_globals[qname] = (elem, schema)
                except AttributeError:
                    xsd_globals[qname] = [xsd_globals[qname], (elem, schema)]

        tags = Counter([x[0] for x in redefinitions])
        for qname, elem, schema, redefined_schema in redefinitions:

            # Checks multiple redefinitions
            if tags[qname] > 1:
                tags[qname] = 1

                redefined_schemas = [x[3] for x in redefinitions if x[0] == qname]
                if any(redefined_schemas.count(x) > 1 for x in redefined_schemas):
                    schema.parse_error(
                        "multiple redefinition for {} {!r}".format(local_name(elem.tag), qname), elem
                    )
                else:
                    redefined_schemas = {x[3]: x[2] for x in redefinitions if x[0] == qname}
                    for rs, s in redefined_schemas.items():
                        while True:
                            try:
                                s = redefined_schemas[s]
                            except KeyError:
                                break

                            if s is rs:
                                schema.parse_error(
                                    "circular redefinition for {} {!r}".format(local_name(elem.tag), qname), elem
                                )
                                break

            # Append redefinition
            try:
                xsd_globals[qname].append((elem, schema))
            except KeyError:
                schema.parse_error("not a redefinition!", elem)
                # xsd_globals[qname] = elem, schema
            except AttributeError:
                xsd_globals[qname] = [xsd_globals[qname], (elem, schema)]

    return load_xsd_globals


load_xsd_simple_types = create_load_function(iterchildren_by_tag(XSD_SIMPLE_TYPE))
load_xsd_attributes = create_load_function(iterchildren_by_tag(XSD_ATTRIBUTE))
load_xsd_attribute_groups = create_load_function(iterchildren_by_tag(XSD_ATTRIBUTE_GROUP))
load_xsd_complex_types = create_load_function(iterchildren_by_tag(XSD_COMPLEX_TYPE))
load_xsd_elements = create_load_function(iterchildren_by_tag(XSD_ELEMENT))
load_xsd_groups = create_load_function(iterchildren_by_tag(XSD_GROUP))
load_xsd_notations = create_load_function(iterchildren_by_tag(XSD_NOTATION))


def create_lookup_function(xsd_classes):
    if isinstance(xsd_classes, tuple):
        types_desc = ' or '.join([c.__name__ for c in xsd_classes])
    else:
        types_desc = xsd_classes.__name__

    def lookup(global_map, qname, tag_map):
        try:
            obj = global_map[qname]
        except KeyError:
            if '{' in qname:
                raise XMLSchemaKeyError("missing a %s component for %r!" % (types_desc, qname))
            raise XMLSchemaKeyError("missing a %s component for %r! As the name has no namespace "
                                    "maybe a missing default namespace declaration." % (types_desc, qname))
        else:
            if isinstance(obj, xsd_classes):
                return obj

            elif isinstance(obj, tuple):
                # Not built XSD global component without redefinitions
                try:
                    elem, schema = obj
                except ValueError:
                    return obj[0]  # Circular build, simply return (elem, schema) couple

                try:
                    factory_or_class = tag_map[elem.tag]
                except KeyError:
                    raise XMLSchemaKeyError("wrong element %r for map %r." % (elem, global_map))

                global_map[qname] = obj,  # Encapsulate into a single-item tuple to catch circular builds
                global_map[qname] = factory_or_class(elem, schema, parent=None)
                return global_map[qname]

            elif isinstance(obj, list):
                # Not built XSD global component with redefinitions
                try:
                    elem, schema = obj[0]
                except ValueError:
                    return obj[0][0]  # Circular build, simply return (elem, schema) couple

                try:
                    factory_or_class = tag_map[elem.tag]
                except KeyError:
                    raise XMLSchemaKeyError("wrong element %r for map %r." % (elem, global_map))

                global_map[qname] = obj[0],  # To catch circular builds
                global_map[qname] = component = factory_or_class(elem, schema, parent=None)

                # Apply redefinitions (changing elem involve a re-parsing of the component)
                for elem, schema in obj[1:]:
                    component.redefine = component.copy()
                    component.redefine.parent = component
                    component.schema = schema
                    component.elem = elem

                return global_map[qname]

            else:
                raise XMLSchemaTypeError(
                    "wrong instance %s for XSD global %r, a %s required." % (obj, qname, types_desc)
                )

    return lookup


lookup_notation = create_lookup_function(XsdNotation)
lookup_type = create_lookup_function((XsdSimpleType, XsdComplexType))
lookup_attribute = create_lookup_function(XsdAttribute)
lookup_attribute_group = create_lookup_function(XsdAttributeGroup)
lookup_group = create_lookup_function(XsdGroup)
lookup_element = create_lookup_function(XsdElement)


class XsdGlobals(XsdValidator):
    """
    Mediator class for related XML schema instances. It stores the global
    declarations defined in the registered schemas. Register a schema to
    add it's declarations to the global maps.

    :param validator: the origin schema class/instance used for creating the global maps.
    :param validation: the XSD validation mode to use, can be 'strict', 'lax' or 'skip'.
    """
    def __init__(self, validator, validation='strict'):
        super(XsdGlobals, self).__init__(validation)
        if not all(hasattr(validator, a) for a in ('meta_schema', 'BUILDERS_MAP')):
            raise XMLSchemaValueError("The argument {!r} is not an XSD schema validator".format(validator))

        self.validator = validator
        self.namespaces = NamespaceResourcesMap()  # Registered schemas by namespace URI

        self.types = {}                 # Global types (both complex and simple)
        self.attributes = {}            # Global attributes
        self.attribute_groups = {}      # Attribute groups
        self.groups = {}                # Model groups
        self.notations = {}             # Notations
        self.elements = {}              # Global elements
        self.substitution_groups = {}   # Substitution groups
        self.constraints = {}           # Constraints (uniqueness, keys, keyref)

        self.global_maps = (self.notations, self.types, self.attributes,
                            self.attribute_groups, self.groups, self.elements)

    def __repr__(self):
        return '%s(validator=%r, validation=%r)' % (self.__class__.__name__, self.validator, self.validation)

    def copy(self, validator=None, validation=None):
        """Makes a copy of the object."""
        obj = XsdGlobals(self.validator if validator is None else validator, validation or self.validation)
        obj.namespaces.update(self.namespaces)
        obj.types.update(self.types)
        obj.attributes.update(self.attributes)
        obj.attribute_groups.update(self.attribute_groups)
        obj.groups.update(self.groups)
        obj.notations.update(self.notations)
        obj.elements.update(self.elements)
        obj.substitution_groups.update(self.substitution_groups)
        obj.constraints.update(self.constraints)
        return obj

    __copy__ = copy

    def lookup_notation(self, qname):
        return lookup_notation(self.notations, qname, self.validator.BUILDERS_MAP)

    def lookup_type(self, qname):
        return lookup_type(self.types, qname, self.validator.BUILDERS_MAP)

    def lookup_attribute(self, qname):
        return lookup_attribute(self.attributes, qname, self.validator.BUILDERS_MAP)

    def lookup_attribute_group(self, qname):
        return lookup_attribute_group(self.attribute_groups, qname, self.validator.BUILDERS_MAP)

    def lookup_group(self, qname):
        return lookup_group(self.groups, qname, self.validator.BUILDERS_MAP)

    def lookup_element(self, qname):
        return lookup_element(self.elements, qname, self.validator.BUILDERS_MAP)

    def lookup(self, tag, qname):
        if tag in (XSD_SIMPLE_TYPE, XSD_COMPLEX_TYPE):
            return self.lookup_type(qname)
        elif tag == XSD_ELEMENT:
            return self.lookup_element(qname)
        elif tag == XSD_GROUP:
            return self.lookup_group(qname)
        elif tag == XSD_ATTRIBUTE:
            return self.lookup_attribute(qname)
        elif tag == XSD_ATTRIBUTE_GROUP:
            return self.lookup_attribute_group(qname)
        elif tag == XSD_NOTATION:
            return self.lookup_notation(qname)
        else:
            raise XMLSchemaValueError("wrong tag {!r} for an XSD global definition/declaration".format(tag))

    @property
    def built(self):
        for schema in self.iter_schemas():
            if not schema.built:
                return False
        return True

    @property
    def validation_attempted(self):
        if self.built:
            return 'full'
        elif any([schema.validation_attempted == 'partial' for schema in self.iter_schemas()]):
            return 'partial'
        else:
            return 'none'

    @property
    def validity(self):
        if not self.namespaces:
            return False
        if all(schema.validity == 'valid' for schema in self.iter_schemas()):
            return 'valid'
        elif any(schema.validity == 'invalid' for schema in self.iter_schemas()):
            return 'invalid'
        else:
            return 'notKnown'

    @property
    def resources(self):
        return [(schema.url, schema) for schemas in self.namespaces.values() for schema in schemas]

    @property
    def all_errors(self):
        errors = []
        for schema in self.iter_schemas():
            errors.extend(schema.all_errors)
        return errors

    def iter_components(self, xsd_classes=None):
        if xsd_classes is None or isinstance(self, xsd_classes):
            yield self
        for xsd_global in self.iter_globals():
            for obj in xsd_global.iter_components(xsd_classes):
                yield obj

    def iter_schemas(self):
        """Creates an iterator for the schemas registered in the instance."""
        for ns_schemas in self.namespaces.values():
            for schema in ns_schemas:
                yield schema

    def iter_globals(self):
        """
        Creates an iterator for XSD global definitions/declarations.
        """
        for global_map in self.global_maps:
            for obj in global_map.values():
                yield obj

    def register(self, schema):
        """
        Registers an XMLSchema instance.
        """
        try:
            ns_schemas = self.namespaces[schema.target_namespace]
        except KeyError:
            self.namespaces[schema.target_namespace] = [schema]
        else:
            if schema in ns_schemas:
                return
            elif not any([schema.url == obj.url and schema.__class__ == obj.__class__ for obj in ns_schemas]):
                ns_schemas.append(schema)

    def clear(self, remove_schemas=False, only_unbuilt=False):
        """
        Clears the instance maps and schemas.

        :param remove_schemas: removes also the schema instances.
        :param only_unbuilt: removes only not built objects/schemas.
        """
        if only_unbuilt:
            not_built_schemas = {schema for schema in self.iter_schemas() if not schema.built}
            if not not_built_schemas:
                return

            for global_map in self.global_maps:
                for k in list(global_map.keys()):
                    obj = global_map[k]
                    if not isinstance(obj, XsdComponent) or obj.schema in not_built_schemas:
                        del global_map[k]
                        if k in self.substitution_groups:
                            del self.substitution_groups[k]
                        if k in self.constraints:
                            del self.constraints[k]

            if remove_schemas:
                namespaces = NamespaceResourcesMap()
                for uri, value in self.namespaces.items():
                    for schema in value:
                        if schema not in not_built_schemas:
                            namespaces[uri] = schema
                self.namespaces = namespaces

        else:
            for global_map in self.global_maps:
                global_map.clear()
            self.substitution_groups.clear()
            self.constraints.clear()

            if remove_schemas:
                self.namespaces.clear()

    def build(self):
        """
        Build the maps of XSD global definitions/declarations. The global maps are
        updated adding and building the globals of not built registered schemas.
        """
        try:
            meta_schema = self.namespaces[XSD_NAMESPACE][0]
        except KeyError:
            # Meta-schemas are not registered. If any of base namespaces is already registered
            # create a new meta-schema, otherwise register the meta-schemas.
            meta_schema = self.validator.meta_schema
            if meta_schema is None:
                raise XMLSchemaValueError("{!r} has not a meta-schema".format(self.validator))

            if any(ns in self.namespaces for ns in meta_schema.BASE_SCHEMAS):
                base_schemas = {k: v for k, v in meta_schema.BASE_SCHEMAS.items() if k not in self.namespaces}
                meta_schema = self.validator.create_meta_schema(meta_schema.url, base_schemas, self)
                for schema in self.iter_schemas():
                    if schema.meta_schema is not None:
                        schema.meta_schema = meta_schema
            else:
                for schema in meta_schema.maps.iter_schemas():
                    self.register(schema)

                self.types.update(meta_schema.maps.types)
                self.attributes.update(meta_schema.maps.attributes)
                self.attribute_groups.update(meta_schema.maps.attribute_groups)
                self.groups.update(meta_schema.maps.groups)
                self.notations.update(meta_schema.maps.notations)
                self.elements.update(meta_schema.maps.elements)
                self.substitution_groups.update(meta_schema.maps.substitution_groups)
                self.constraints.update(meta_schema.maps.constraints)

        not_built_schemas = [schema for schema in self.iter_schemas() if not schema.built]
        for schema in not_built_schemas:
            schema._root_elements = None

        # Load and build global declarations
        load_xsd_notations(self.notations, not_built_schemas)
        load_xsd_simple_types(self.types, not_built_schemas)
        load_xsd_attributes(self.attributes, not_built_schemas)
        load_xsd_attribute_groups(self.attribute_groups, not_built_schemas)
        load_xsd_complex_types(self.types, not_built_schemas)
        load_xsd_elements(self.elements, not_built_schemas)
        load_xsd_groups(self.groups, not_built_schemas)

        if not meta_schema.built:
            xsd_builtin_types_factory(meta_schema, self.types)

        for qname in self.notations:
            self.lookup_notation(qname)
        for qname in self.attributes:
            self.lookup_attribute(qname)
        for qname in self.attribute_groups:
            self.lookup_attribute_group(qname)
        for qname in self.types:
            self.lookup_type(qname)
        for qname in self.elements:
            self.lookup_element(qname)
        for qname in self.groups:
            self.lookup_group(qname)

        # Builds element declarations inside model groups.
        for schema in not_built_schemas:
            for group in schema.iter_components(XsdGroup):
                group.build()

        for schema in filter(lambda x: x.meta_schema is not None, not_built_schemas):
            # Build key references and assertions (XSD meta-schema doesn't have any of them)
            for constraint in schema.iter_components(XsdKeyref):
                constraint.parse_refer()
            for assertion in schema.iter_components(XsdAssert):
                assertion.parse()
            self._check_schema(schema)

        if self.validation == 'strict' and not self.built:
            raise XMLSchemaNotBuiltError(self, "global map %r not built!" % self)

    def _check_schema(self, schema):
        # Checks substitution groups circularities
        for qname in self.substitution_groups:
            xsd_element = self.elements[qname]
            for e in xsd_element.iter_substitutes():
                if e is xsd_element:
                    schema.parse_error("circularity found for substitution group with head element %r" % xsd_element)

        if schema.XSD_VERSION > '1.0' and schema.default_attributes is not None:
            if not isinstance(schema.default_attributes, XsdAttributeGroup):
                schema.default_attributes = None
                schema.parse_error("defaultAttributes={!r} doesn't match an attribute group of {!r}"
                                   .format(schema.root.get('defaultAttributes'), schema), schema.root)

        if schema.validation == 'skip':
            return

        # Check redefined global groups
        for group in filter(lambda x: x.schema is schema and x.redefine is not None, self.groups.values()):
            if not any(isinstance(e, XsdGroup) and e.name == group.name for e in group) \
                    and not group.is_restriction(group.redefine):
                group.parse_error("The redefined group is an illegal restriction of the original group.")

        # Check complex content types models
        for xsd_type in schema.iter_components(XsdComplexType):
            if not isinstance(xsd_type.content_type, XsdGroup):
                continue

            base_type = xsd_type.base_type
            if xsd_type.derivation == 'restriction':
                if base_type and base_type.name != XSD_ANY_TYPE and base_type.is_complex():
                    if not xsd_type.content_type.is_restriction(base_type.content_type):
                        xsd_type.parse_error("The derived group is an illegal restriction of the base type group.")

            try:
                xsd_type.content_type.check_model()
            except XMLSchemaModelDepthError:
                msg = "cannot verify the content model of %r due to maximum recursion depth exceeded" % xsd_type
                schema.warnings.append(msg)
                warnings.warn(msg, XMLSchemaWarning, stacklevel=4)
            except XMLSchemaModelError as err:
                if self.validation == 'strict':
                    raise
                xsd_type.errors.append(err)
