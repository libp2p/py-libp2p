"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import runtime_version as _runtime_version
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC,
    6,
    31,
    1,
    '',
    'ipns.proto'
)
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\nipns.proto\x12\x07ipns.pb\"\xe3\x01\n\tIpnsEntry\x12\r\n\x05value\x18\x01 \x01(\x0c\x12\x13\n\x0bsignatureV1\x18\x02 \x01(\x0c\x12\x35\n\x0cvalidityType\x18\x03 \x01(\x0e\x32\x1f.ipns.pb.IpnsEntry.ValidityType\x12\x10\n\x08validity\x18\x04 \x01(\x0c\x12\x10\n\x08sequence\x18\x05 \x01(\x04\x12\x0b\n\x03ttl\x18\x06 \x01(\x04\x12\x0e\n\x06pubKey\x18\x07 \x01(\x0c\x12\x13\n\x0bsignatureV2\x18\x08 \x01(\x0c\x12\x0c\n\x04\x64\x61ta\x18\t \x01(\x0c\"\x17\n\x0cValidityType\x12\x07\n\x03\x45OL\x10\x00\x62\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'ipns_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
  DESCRIPTOR._loaded_options = None
  _globals['_IPNSENTRY']._serialized_start=24
  _globals['_IPNSENTRY']._serialized_end=251
  _globals['_IPNSENTRY_VALIDITYTYPE']._serialized_start=228
  _globals['_IPNSENTRY_VALIDITYTYPE']._serialized_end=251
# @@protoc_insertion_point(module_scope)
