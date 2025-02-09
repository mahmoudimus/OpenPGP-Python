from __future__ import absolute_import

import collections
import copy
import hashlib
import math
import sys
from struct import pack, unpack

import Crypto.Cipher.AES
import Crypto.Cipher.Blowfish
import Crypto.Cipher.CAST
import Crypto.Cipher.DES3
import Crypto.Cipher.PKCS1_v1_5
import Crypto.Hash.MD5
import Crypto.Hash.RIPEMD
import Crypto.Hash.SHA
import Crypto.Hash.SHA224
import Crypto.Hash.SHA256
import Crypto.Hash.SHA384
import Crypto.Hash.SHA512
import Crypto.PublicKey.DSA
import Crypto.Signature.DSS
import Crypto.PublicKey.RSA
import Crypto.Random
import Crypto.Random.random
import Crypto.Signature.PKCS1_v1_5
import Crypto.Util.number

import OpenPGP

__all__ = ["Wrapper"]


class Wrapper:
    """A wrapper for using the classes from OpenPGP.py with PyCrypto"""

    def __init__(self, packet):
        packet = self._parse_packet(packet)
        self._key = self._message = None
        if isinstance(packet, OpenPGP.PublicKeyPacket) or (
            hasattr(packet, "__getitem__")
            and isinstance(packet[0], OpenPGP.PublicKeyPacket)
        ):  # If it's a key (other keys are subclasses of this one)
            self._key = packet
        else:
            self._message = packet

    def key(self, keyid=None):
        if not self._key:  # No key
            return None
        if isinstance(self._key, OpenPGP.Message):
            for p in self._key:
                if isinstance(p, OpenPGP.PublicKeyPacket):
                    if (
                        not keyid
                        or p.fingerprint()[len(keyid) * -1 :].upper() == keyid.upper()
                    ):
                        return p
        return self._key

    def public_key(self, keyid=None):
        """Get RsaKey or DsaKey for the public key"""
        return self.convert_public_key(self.key(keyid))

    def private_key(self, keyid=None):
        """Get RsaKey or DsaKey for the public key"""
        return self.convert_private_key(self.key(keyid))

    def encrypted_data(self):
        if not self._message:
            return None

        for p in self._message:
            if isinstance(p, OpenPGP.EncryptedDataPacket):
                return p

        return None

    def verifier(self, h, m, s):
        """Used in implementation of verify"""
        key = self.public_key(s.issuer())
        if not key or (
            s.key_algorithm_name() == "DSA"
            and not isinstance(key, Crypto.PublicKey.DSA.DsaKey)
        ):
            return False
        if s.key_algorithm_name() == "DSA":
            if len(s.data) == 1:
                signature = s.data[0]
            elif len(s.data) == 2: 
                signature = s.data[0] + s.data[1]
            else:
                raise ValueError("Unexpected length in s.data %s!" % len(s.data))

            verifier = Crypto.Signature.DSS.new(key, 'fips-186-3')           
            try:
                verifier.verify(h.new(m), signature)
                return True
            except ValueError as e:
                print("signature verification failed!", e, file=sys.stderr)
                return False
        else:  # RSA
            protocol = Crypto.Signature.PKCS1_v1_5.new(key)
            return protocol.verify(h.new(m), s.data[0])

    def verify(self, packet):
        """Pass a message to verify with this key, or a key (OpenPGP, RsaKey, or DsaKey)
        to check this message with
        Second optional parameter to specify which signature to verify (if there is more than one)
        """
        m = None
        packet = self._parse_packet(packet)
        if not self._message:
            m = packet
            verifier = self.verifier
        else:
            m = self._message
            verifier = self.__class__(packet).verifier

        hashes = {
            "MD5": lambda m, s: verifier(Crypto.Hash.MD5, m, s),
            "RIPEMD160": lambda m, s: verifier(Crypto.Hash.RIPEMD, m, s),
            "SHA1": lambda m, s: verifier(Crypto.Hash.SHA, m, s),
            "SHA224": lambda m, s: verifier(Crypto.Hash.SHA224, m, s),
            "SHA256": lambda m, s: verifier(Crypto.Hash.SHA256, m, s),
            "SHA384": lambda m, s: verifier(Crypto.Hash.SHA384, m, s),
            "SHA512": lambda m, s: verifier(Crypto.Hash.SHA512, m, s),
        }

        return m.verified_signatures({"RSA": hashes, "DSA": hashes})

    def sign(self, packet, hash="SHA256", keyid=None):
        if (
            self._key
            and not isinstance(packet, OpenPGP.Packet)
            and not isinstance(packet, OpenPGP.Message)
        ):
            packet = OpenPGP.LiteralDataPacket(packet)
        else:
            packet = self._parse_packet(packet)

        if (
            isinstance(packet, OpenPGP.SecretKeyPacket)
            or isinstance(packet, Crypto.PublicKey.RSA.RsaKey)
            or isinstance(packet, Crypto.PublicKey.DSA.DsaKey)
            or (
                hasattr(packet, "__getitem__")
                and isinstance(packet[0], OpenPGP.SecretKeyPacket)
            )
        ):
            key = packet
            message = self._message
        else:
            key = self._key
            message = packet

        if not key or not message:
            return None  # Missing some data

        if isinstance(message, OpenPGP.Message):
            message = message.signature_and_data()[1]

        if not (
            isinstance(key, Crypto.PublicKey.RSA.RsaKey)
            or isinstance(packet, Crypto.PublicKey.DSA.DsaKey)
        ):
            key = self.__class__(key)
            if not keyid:
                keyid = key.key().fingerprint()[-16:]
            key = key.private_key(keyid)

        key_algorithm = None
        if isinstance(key, Crypto.PublicKey.RSA.RsaKey):
            key_algorithm = "RSA"
        elif isinstance(key, Crypto.PublicKey.DSA.DsaKey):
            key_algorithm = "DSA"

        sig = OpenPGP.SignaturePacket(message, key_algorithm, hash.upper())

        if keyid:
            sig.hashed_subpackets.append(OpenPGP.SignaturePacket.IssuerPacket(keyid))

        def doDSA(h, m):
            signer = Crypto.Signature.DSS.new(key, 'fips-186-3')
            signature = signer.sign(h.new(m))
            return [signature]

        sig.sign_data(
            {
                "RSA": {
                    "MD5": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.MD5.new(m)
                        )
                    ],
                    "RIPEMD160": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.RIPEMD.new(m)
                        )
                    ],
                    "SHA1": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.SHA.new(m)
                        )
                    ],
                    "SHA224": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.SHA224.new(m)
                        )
                    ],
                    "SHA256": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.SHA256.new(m)
                        )
                    ],
                    "SHA384": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.SHA384.new(m)
                        )
                    ],
                    "SHA512": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.SHA512.new(m)
                        )
                    ],
                },
                "DSA": {
                    "MD5": lambda m: doDSA(Crypto.Hash.MD5, m),
                    "RIPEMD160": lambda m: doDSA(Crypto.Hash.RIPEMD, m),
                    "SHA1": lambda m: doDSA(Crypto.Hash.SHA, m),
                    "SHA224": lambda m: doDSA(Crypto.Hash.SHA224, m),
                    "SHA256": lambda m: doDSA(Crypto.Hash.SHA256, m),
                    "SHA384": lambda m: doDSA(Crypto.Hash.SHA384, m),
                    "SHA512": lambda m: doDSA(Crypto.Hash.SHA512, m),
                },
            }
        )

        return OpenPGP.Message([sig, message])

    # TODO: merge this with the normal sign function
    def sign_key_userid(self, packet, hash="SHA256", keyid=None):
        if isinstance(packet, list):
            packet = OpenPGP.Message(packet)
        elif not isinstance(packet, OpenPGP.Message):
            packet = OpenPGP.Message.parse(packet)

        key = self.key(keyid)
        if not key or not packet:  # Missing some data
            return None

        if not keyid:
            keyid = key.fingerprint()[-16:]

        key = self.private_key(keyid)

        sig = None
        for p in packet:
            if isinstance(p, OpenPGP.SignaturePacket):
                sig = p
        if not sig:
            sig = OpenPGP.SignaturePacket(packet, "RSA", hash.upper())
            sig.signature_type = 0x13
            sig.hashed_subpackets.append(OpenPGP.SignaturePacket.KeyFlagsPacket([0x01]))
            sig.hashed_subpackets.append(OpenPGP.SignaturePacket.IssuerPacket(keyid))
            packet.append(sig)

        def doDSA(h, m):
            return list(
                key.sign(
                    h.new(m).digest()[0 : int(Crypto.Util.number.size(key.q) / 8)],
                    Crypto.Random.random.StrongRandom().randint(1, key.q - 1),
                )
            )

        sig.sign_data(
            {
                "RSA": {
                    "MD5": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.MD5.new(m)
                        )
                    ],
                    "RIPEMD160": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.RIPEMD.new(m)
                        )
                    ],
                    "SHA1": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.SHA.new(m)
                        )
                    ],
                    "SHA224": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.SHA224.new(m)
                        )
                    ],
                    "SHA256": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.SHA256.new(m)
                        )
                    ],
                    "SHA384": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.SHA384.new(m)
                        )
                    ],
                    "SHA512": lambda m: [
                        Crypto.Signature.PKCS1_v1_5.new(key).sign(
                            Crypto.Hash.SHA512.new(m)
                        )
                    ],
                },
                "DSA": {
                    "MD5": lambda m: doDSA(Crypto.Hash.MD5, m),
                    "RIPEMD160": lambda m: doDSA(Crypto.Hash.RIPEMD, m),
                    "SHA1": lambda m: doDSA(Crypto.Hash.SHA, m),
                    "SHA224": lambda m: doDSA(Crypto.Hash.SHA224, m),
                    "SHA256": lambda m: doDSA(Crypto.Hash.SHA256, m),
                    "SHA384": lambda m: doDSA(Crypto.Hash.SHA384, m),
                    "SHA512": lambda m: doDSA(Crypto.Hash.SHA512, m),
                },
            }
        )

        return packet

    def decrypt(self, packet):
        if isinstance(packet, list):
            packet = OpenPGP.Message(packet)
        elif not isinstance(packet, OpenPGP.Message):
            packet = OpenPGP.Message.parse(packet)

        if (
            isinstance(packet, OpenPGP.SecretKeyPacket)
            or isinstance(packet, Crypto.PublicKey.RSA.RsaKey)
            or (
                hasattr(packet, "__getitem__")
                and isinstance(packet[0], OpenPGP.SecretKeyPacket)
            )
        ):
            keys = packet
        else:
            keys = self._key
            self._message = packet

        if not keys or not self._message:
            return None  # Missing some data

        if not isinstance(keys, Crypto.PublicKey.RSA.RsaKey):
            keys = self.__class__(keys)

        for p in self._message:
            if isinstance(p, OpenPGP.AsymmetricSessionKeyPacket):
                if isinstance(keys, Crypto.PublicKey.RSA.RsaKey):
                    sk = self.try_decrypt_session(keys, p.encrypted_data[2:])
                elif len(p.keyid.replace("0", "")) < 1:
                    for k in keys.key:
                        sk = self.try_decrypt_session(
                            self.convert_private_key(k), p.encyrpted_data[2:]
                        )
                        if sk:
                            break
                else:
                    key = keys.private_key(p.keyid)
                    sk = self.try_decrypt_session(key, p.encrypted_data[2:])

                if not sk:
                    continue

                r = self.decrypt_packet(self.encrypted_data(), sk[0], sk[1])
                if r:
                    return r

        return None  # Failed

    @classmethod
    def try_decrypt_session(cls, key, edata):
        pkcs15 = Crypto.Cipher.PKCS1_v1_5.new(key)
        data = pkcs15.decrypt(edata, Crypto.Random.new().read(len(edata)))
        sk = data[1 : len(data) - 2]
        chk = unpack("!H", data[-2:])[0]

        sk_chk = 0
        for i in range(0, len(sk)):
            sk_chk = (sk_chk + ord(sk[i : i + 1])) % 65536

        if sk_chk != chk:
            return None
        return (ord(data[0:1]), sk)

    def encrypt(self, passphrases_and_keys, symmetric_algorithm=9):
        cipher, key_bytes, key_block_bytes = self.get_cipher(symmetric_algorithm)
        if not cipher:
            raise Exception("Unsupported cipher")
        prefix = Crypto.Random.new().read(key_block_bytes)
        prefix += prefix[-2:]

        key = Crypto.Random.new().read(key_bytes)
        session_cipher = cipher(key)(None)

        to_encrypt = prefix + self._message.to_bytes()
        mdc = OpenPGP.ModificationDetectionCodePacket(
            Crypto.Hash.SHA.new(to_encrypt + b"\xD3\x14").digest()
        )
        to_encrypt += mdc.to_bytes()

        encrypted = [
            OpenPGP.IntegrityProtectedDataPacket(
                self._block_pad_unpad(
                    key_block_bytes, to_encrypt, lambda x: session_cipher.encrypt(x)
                )
            )
        ]

        if not isinstance(passphrases_and_keys, collections.Iterable) or hasattr(
            passphrases_and_keys, "encode"
        ):
            passphrases_and_keys = [passphrases_and_keys]

        for psswd in passphrases_and_keys:
            if isinstance(psswd, OpenPGP.PublicKeyPacket):
                if not psswd.key_algorithm in [1, 2, 3]:
                    raise Exception("Only RSA keys are supported.")
                rsa = self.__class__(psswd).public_key()
                pkcs1 = Crypto.Cipher.PKCS1_v1_5.new(rsa)
                esk = pkcs1.encrypt(
                    pack("!B", symmetric_algorithm)
                    + key
                    + pack("!H", OpenPGP.checksum(key))
                )
                esk = pack("!H", OpenPGP.bitlength(esk)) + esk
                encrypted = [
                    OpenPGP.AsymmetricSessionKeyPacket(
                        psswd.key_algorithm, psswd.fingerprint(), esk
                    )
                ] + encrypted
            elif hasattr(psswd, "encode"):
                psswd = psswd.encode("utf-8")
                s2k = OpenPGP.S2K(Crypto.Random.new().read(10))
                packet_cipher = cipher(s2k.make_key(psswd, key_bytes))(None)
                esk = self._block_pad_unpad(
                    key_block_bytes,
                    pack("!B", symmetric_algorithm) + key,
                    lambda x: packet_cipher.encrypt(x),
                )
                encrypted = [
                    OpenPGP.SymmetricSessionKeyPacket(s2k, esk, symmetric_algorithm)
                ] + encrypted

        return OpenPGP.Message(encrypted)

    def decrypt_symmetric(self, passphrase):
        epacket = self.encrypted_data()
        if hasattr(passphrase, "encode"):
            passphrase = passphrase.encode("utf-8")

        decrypted = None
        for p in self._message:
            if isinstance(p, OpenPGP.SymmetricSessionKeyPacket):
                if len(p.encrypted_data) > 0:
                    cipher, key_bytes, key_block_bytes = self.get_cipher(
                        p.symmetric_algorithm
                    )
                    if not cipher:
                        continue
                    cipher = cipher(p.s2k.make_key(passphrase, key_bytes))
                    data = self._block_pad_unpad(
                        key_block_bytes,
                        p.encrypted_data,
                        lambda x: cipher(None).decrypt(x),
                    )

                    decrypted = self.decrypt_packet(epacket, ord(data[0:1]), data[1:])
                else:
                    cipher, key_bytes, key_block_bytes = self.get_cipher(
                        p.symmetric_algorithm
                    )
                    if not cipher:
                        continue

                    decrypted = self.decrypt_packet(
                        epacket,
                        p.symmetric_algorithm,
                        p.s2k.make_key(passphrase, key_bytes),
                    )

                if decrypted:
                    return decrypted

        return None  # If we get here, we failed

    def decrypt_secret_key(self, passphrase):
        if hasattr(passphrase, "encode"):
            passphrase = passphrase.encode("utf-8")

        packet = copy.copy(self._message or self._key)  # Do not mutate original

        cipher, key_bytes, key_block_bytes = self.get_cipher(packet.symmetric_algorithm)
        cipher = cipher(packet.s2k.make_key(passphrase, key_bytes))
        cipher = cipher(packet.encrypted_data[:key_block_bytes])
        material = self._block_pad_unpad(
            key_block_bytes,
            packet.encrypted_data[key_block_bytes:],
            lambda x: cipher.decrypt(x),
        )

        if packet.s2k_useage == 254:
            chk = material[-20:]
            material = material[:-20]
            if chk != hashlib.sha1(material):
                return None
        else:
            chk = unpack("!H", material[-2:])[0]
            material = material[:-2]
            if chk != OpenPGP.checksum(material):
                return None

        packet.s2k_usage = 0
        packet.symmetric_alorithm = 0
        packet.encrypted_data = None
        packet.input = OpenPGP.PushbackGenerator(OpenPGP._gen_one(material))
        packet.length = len(material)
        packet.key_from_input()
        packet.input = None
        return packet

    @classmethod
    def decrypt_packet(cls, epacket, symmetric_algorithm, key):
        cipher, key_bytes, key_block_bytes = cls.get_cipher(symmetric_algorithm)
        if not cipher:
            return None
        cipher = cipher(key)

        if isinstance(epacket, OpenPGP.IntegrityProtectedDataPacket):
            data = cls._block_pad_unpad(
                key_block_bytes, epacket.data, lambda x: cipher(None).decrypt(x)
            )
            prefix = data[0 : key_block_bytes + 2]
            mdc = data[-22:][2:]
            data = data[key_block_bytes + 2 : -22]

            mkMDC = hashlib.sha1(prefix + data + b"\xd3\x14").digest()
            if mdc != mkMDC:
                return False

            try:
                return OpenPGP.Message.parse(data)
            except:
                return None
        else:
            # No MDC means decrypt with resync
            edata = epacket.data[key_block_bytes + 2 :]
            data = cls._block_pad_unpad(
                key_block_bytes,
                edata,
                lambda x: cipher(epacket.data[2 : key_block_bytes + 2]).decrypt(x),
            )
            try:
                return OpenPGP.Message.parse(data)
            except:
                return None

        return None

    @classmethod
    def _parse_packet(cls, packet):
        if (
            isinstance(packet, OpenPGP.Packet)
            or isinstance(packet, OpenPGP.Message)
            or isinstance(packet, Crypto.PublicKey.RSA.RsaKey)
            or isinstance(packet, Crypto.PublicKey.DSA.DsaKey)
        ):
            return packet
        elif isinstance(packet, tuple) or isinstance(packet, list):
            if (
                sys.version_info[0] == 2
                and isinstance(packet[0], long)
                or isinstance(packet[0], int)
            ):
                data = []
                for i in packet:
                    data.append(
                        Crypto.Util.number.long_to_bytes(i)
                    )  # OpenPGP likes bytes
            else:
                data = packet
            return OpenPGP.SecretKeyPacket(
                keydata=data, algorithm=1, version=3
            )  # V3 for fingerprint with no timestamp
        else:
            return OpenPGP.Message.parse(packet)

    @classmethod
    def get_cipher(cls, algo):
        def cipher(m, ks, bs):
            return (
                lambda k: lambda iv: m.new(
                    k,
                    mode=m.MODE_CFB,
                    IV=iv or b"\0" * bs,
                    segment_size=bs * 8,
                ),
                ks,
                bs,
            )

        if algo == 2:
            return cipher(Crypto.Cipher.DES3, 24, 8)
        elif algo == 3:
            return cipher(Crypto.Cipher.CAST, 16, 8)
        elif algo == 4:
            return cipher(Crypto.Cipher.Blowfish, 16, 8)
        elif algo == 7:
            return cipher(Crypto.Cipher.AES, 16, 16)
        elif algo == 8:
            return cipher(Crypto.Cipher.AES, 24, 16)
        elif algo == 9:
            return cipher(Crypto.Cipher.AES, 32, 16)

        return (None, None, None)  # Not supported

    @classmethod
    def convert_key(cls, packet, private=False):
        if isinstance(packet, Crypto.PublicKey.RSA.RsaKey) or isinstance(
            packet, Crypto.PublicKey.DSA.DsaKey
        ):
            return packet
        packet = cls._parse_packet(packet)
        if isinstance(packet, OpenPGP.Message):
            packet = packet[0]

        if packet.key_algorithm_name() == "DSA":
            public = (
                Crypto.Util.number.bytes_to_long(packet.key["y"]),
                Crypto.Util.number.bytes_to_long(packet.key["g"]),
                Crypto.Util.number.bytes_to_long(packet.key["p"]),
                Crypto.Util.number.bytes_to_long(packet.key["q"]),
            )
            if private:
                private = (Crypto.Util.number.bytes_to_long(packet.key["x"]),)
                return Crypto.PublicKey.DSA.construct(public + private)
            else:
                return Crypto.PublicKey.DSA.construct(public)
        else:  # RSA
            public = (
                Crypto.Util.number.bytes_to_long(packet.key["n"]),
                Crypto.Util.number.bytes_to_long(packet.key["e"]),
            )
            if private:
                private = (Crypto.Util.number.bytes_to_long(packet.key["d"]),)
                if "p" in packet.key:  # Has optional parts
                    private += (
                        Crypto.Util.number.bytes_to_long(packet.key["p"]),
                        Crypto.Util.number.bytes_to_long(packet.key["q"]),
                        Crypto.Util.number.bytes_to_long(packet.key["u"]),
                    )
                return Crypto.PublicKey.RSA.construct(public + private)
            else:
                return Crypto.PublicKey.RSA.construct(public)

    @classmethod
    def convert_public_key(cls, packet):
        return cls.convert_key(packet, False)

    @classmethod
    def convert_private_key(cls, packet):
        return cls.convert_key(packet, True)

    @classmethod
    def _block_pad_unpad(cls, siz, bs, go):
        pad_amount = siz - (len(bs) % siz)
        return go(bs + b"\0" * pad_amount)[:-pad_amount]
