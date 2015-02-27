# Authors: 
#   Trevor Perrin
#   Google - added reqCAs parameter
#   Google (adapted by Sam Rushing and Marcelo Fernandez) - NPN support
#   Dimitris Moraitis - Anon ciphersuites
#   Martin von Loewis - python 3 port
#   Yngve Pettersen (ported by Paul Sokolovsky) - TLS 1.2
#
# See the LICENSE file for legal information regarding use of this file.

"""
MAIN CLASS FOR TLS LITE (START HERE!).
"""

import socket
from .utils.compat import formatExceptionTrace
from .tlsrecordlayer import TLSRecordLayer
from .session import Session
from .constants import *
from .utils.cryptomath import getRandomBytes
from .errors import *
from .messages import *
from .mathtls import *
from .handshakesettings import HandshakeSettings
from .utils.tackwrapper import *
from .verifiers import ServerHelloVerifier
from .handshakehashes import HandshakeHashes


class TLSConnection(TLSRecordLayer):
    """
    This class wraps a socket and provides TLS handshaking and data
    transfer.

    To use this class, create a new instance, passing a connected
    socket into the constructor.  Then call some handshake function.
    If the handshake completes without raising an exception, then a TLS
    connection has been negotiated.  You can transfer data over this
    connection as if it were a socket.

    This class provides both synchronous and asynchronous versions of
    its key functions.  The synchronous versions should be used when
    writing single-or multi-threaded code using blocking sockets.  The
    asynchronous versions should be used when performing asynchronous,
    event-based I/O with non-blocking sockets.

    Asynchronous I/O is a complicated subject; typically, you should
    not use the asynchronous functions directly, but should use some
    framework like asyncore or Twisted which TLS Lite integrates with
    (see
    L{tlslite.integration.tlsasyncdispatchermixin.TLSAsyncDispatcherMixIn}).

    @type resumed: bool
    @ivar resumed: If this connection is based on a resumed session.

    @type allegedSrpUsername: str or None
    @ivar allegedSrpUsername:  This is set to the SRP username
    asserted by the client, whether the handshake succeeded or not.
    If the handshake fails, this can be inspected to determine
    if a guessing attack is in progress against a particular user
    account.
    """

    def __init__(self, sock):
        """Create a new TLSConnection instance.

        @param sock: The socket data will be transmitted on.  The
        socket should already be connected.  It may be in blocking or
        non-blocking mode.

        @type sock: L{socket.socket}
        """
        TLSRecordLayer.__init__(self, sock)

        self._readBuffer = bytearray(0)
        self.resumed = False

        #What username did the client claim in his handshake?
        self.allegedSrpUsername = None
        self._refCount = 0 #Used to trigger closure

        #Handshake digests
        self._handshakeHashes = HandshakeHashes()

    #*********************************************************
    # Client Handshake Functions
    #*********************************************************

    def handshakeClientAnonymous(self, session=None, settings=None, 
                                checker=None, serverName="",
                                async=False):
        """Perform an anonymous handshake in the role of client.

        This function performs an SSL or TLS handshake using an
        anonymous Diffie Hellman ciphersuite.
        
        Like any handshake function, this can be called on a closed
        TLS connection, or on a TLS connection that is already open.
        If called on an open connection it performs a re-handshake.

        If the function completes without raising an exception, the
        TLS connection will be open and available for data transfer.

        If an exception is raised, the connection will have been
        automatically closed (if it was ever open).

        @type session: L{tlslite.Session.Session}
        @param session: A TLS session to attempt to resume.  If the
        resumption does not succeed, a full handshake will be
        performed.

        @type settings: L{tlslite.HandshakeSettings.HandshakeSettings}
        @param settings: Various settings which can be used to control
        the ciphersuites, certificate types, and SSL/TLS versions
        offered by the client.

        @type checker: L{tlslite.Checker.Checker}
        @param checker: A Checker instance.  This instance will be
        invoked to examine the other party's authentication
        credentials, if the handshake completes succesfully.
        
        @type serverName: string
        @param serverName: The ServerNameIndication TLS Extension.

        @type async: bool
        @param async: If False, this function will block until the
        handshake is completed.  If True, this function will return a
        generator.  Successive invocations of the generator will
        return 0 if it is waiting to read from the socket, 1 if it is
        waiting to write to the socket, or will raise StopIteration if
        the handshake operation is completed.

        @rtype: None or an iterable
        @return: If 'async' is True, a generator object will be
        returned.

        @raise socket.error: If a socket error occurs.
        @raise tlslite.errors.TLSAbruptCloseError: If the socket is closed
        without a preceding alert.
        @raise tlslite.errors.TLSAlert: If a TLS alert is signalled.
        @raise tlslite.errors.TLSAuthenticationError: If the checker
        doesn't like the other party's authentication credentials.
        """
        handshaker = self._handshakeClientAsync(anonParams=(True),
                                                session=session,
                                                settings=settings,
                                                checker=checker,
                                                serverName=serverName)
        if async:
            return handshaker
        for result in handshaker:
            pass

    def handshakeClientSRP(self, username, password, session=None,
                           settings=None, checker=None, 
                           reqTack=True, serverName="",
                           async=False):
        """Perform an SRP handshake in the role of client.

        This function performs a TLS/SRP handshake.  SRP mutually
        authenticates both parties to each other using only a
        username and password.  This function may also perform a
        combined SRP and server-certificate handshake, if the server
        chooses to authenticate itself with a certificate chain in
        addition to doing SRP.

        If the function completes without raising an exception, the
        TLS connection will be open and available for data transfer.

        If an exception is raised, the connection will have been
        automatically closed (if it was ever open).

        @type username: str
        @param username: The SRP username.

        @type password: str
        @param password: The SRP password.

        @type session: L{tlslite.session.Session}
        @param session: A TLS session to attempt to resume.  This
        session must be an SRP session performed with the same username
        and password as were passed in.  If the resumption does not
        succeed, a full SRP handshake will be performed.

        @type settings: L{tlslite.handshakesettings.HandshakeSettings}
        @param settings: Various settings which can be used to control
        the ciphersuites, certificate types, and SSL/TLS versions
        offered by the client.

        @type checker: L{tlslite.checker.Checker}
        @param checker: A Checker instance.  This instance will be
        invoked to examine the other party's authentication
        credentials, if the handshake completes succesfully.

        @type reqTack: bool
        @param reqTack: Whether or not to send a "tack" TLS Extension, 
        requesting the server return a TackExtension if it has one.

        @type serverName: string
        @param serverName: The ServerNameIndication TLS Extension.

        @type async: bool
        @param async: If False, this function will block until the
        handshake is completed.  If True, this function will return a
        generator.  Successive invocations of the generator will
        return 0 if it is waiting to read from the socket, 1 if it is
        waiting to write to the socket, or will raise StopIteration if
        the handshake operation is completed.

        @rtype: None or an iterable
        @return: If 'async' is True, a generator object will be
        returned.

        @raise socket.error: If a socket error occurs.
        @raise tlslite.errors.TLSAbruptCloseError: If the socket is closed
        without a preceding alert.
        @raise tlslite.errors.TLSAlert: If a TLS alert is signalled.
        @raise tlslite.errors.TLSAuthenticationError: If the checker
        doesn't like the other party's authentication credentials.
        """
        handshaker = self._handshakeClientAsync(srpParams=(username, password),
                        session=session, settings=settings, checker=checker,
                        reqTack=reqTack, serverName=serverName)
        # The handshaker is a Python Generator which executes the handshake.
        # It allows the handshake to be run in a "piecewise", asynchronous
        # fashion, returning 1 when it is waiting to able to write, 0 when
        # it is waiting to read.
        #
        # If 'async' is True, the generator is returned to the caller, 
        # otherwise it is executed to completion here.  
        if async:
            return handshaker
        for result in handshaker:
            pass

    def handshakeClientCert(self, certChain=None, privateKey=None,
                            session=None, settings=None, checker=None,
                            nextProtos=None, reqTack=True, serverName=None,
                            async=False):
        """Perform a certificate-based handshake in the role of client.

        This function performs an SSL or TLS handshake.  The server
        will authenticate itself using an X.509 certificate
        chain.  If the handshake succeeds, the server's certificate
        chain will be stored in the session's serverCertChain attribute.
        Unless a checker object is passed in, this function does no
        validation or checking of the server's certificate chain.

        If the server requests client authentication, the
        client will send the passed-in certificate chain, and use the
        passed-in private key to authenticate itself.  If no
        certificate chain and private key were passed in, the client
        will attempt to proceed without client authentication.  The
        server may or may not allow this.

        If the function completes without raising an exception, the
        TLS connection will be open and available for data transfer.

        If an exception is raised, the connection will have been
        automatically closed (if it was ever open).

        @type certChain: L{tlslite.x509certchain.X509CertChain}
        @param certChain: The certificate chain to be used if the
        server requests client authentication.

        @type privateKey: L{tlslite.utils.rsakey.RSAKey}
        @param privateKey: The private key to be used if the server
        requests client authentication.

        @type session: L{tlslite.session.Session}
        @param session: A TLS session to attempt to resume.  If the
        resumption does not succeed, a full handshake will be
        performed.

        @type settings: L{tlslite.handshakesettings.HandshakeSettings}
        @param settings: Various settings which can be used to control
        the ciphersuites, certificate types, and SSL/TLS versions
        offered by the client.

        @type checker: L{tlslite.checker.Checker}
        @param checker: A Checker instance.  This instance will be
        invoked to examine the other party's authentication
        credentials, if the handshake completes succesfully.
        
        @type nextProtos: list of strings.
        @param nextProtos: A list of upper layer protocols ordered by
        preference, to use in the Next-Protocol Negotiation Extension.
        
        @type reqTack: bool
        @param reqTack: Whether or not to send a "tack" TLS Extension, 
        requesting the server return a TackExtension if it has one.        

        @type serverName: string
        @param serverName: The ServerNameIndication TLS Extension.

        @type async: bool
        @param async: If False, this function will block until the
        handshake is completed.  If True, this function will return a
        generator.  Successive invocations of the generator will
        return 0 if it is waiting to read from the socket, 1 if it is
        waiting to write to the socket, or will raise StopIteration if
        the handshake operation is completed.

        @rtype: None or an iterable
        @return: If 'async' is True, a generator object will be
        returned.

        @raise socket.error: If a socket error occurs.
        @raise tlslite.errors.TLSAbruptCloseError: If the socket is closed
        without a preceding alert.
        @raise tlslite.errors.TLSAlert: If a TLS alert is signalled.
        @raise tlslite.errors.TLSAuthenticationError: If the checker
        doesn't like the other party's authentication credentials.
        """
        handshaker = self._handshakeClientAsync(certParams=(certChain,
                        privateKey), session=session, settings=settings,
                        checker=checker, serverName=serverName, 
                        nextProtos=nextProtos, reqTack=reqTack)
        # The handshaker is a Python Generator which executes the handshake.
        # It allows the handshake to be run in a "piecewise", asynchronous
        # fashion, returning 1 when it is waiting to able to write, 0 when
        # it is waiting to read.
        #
        # If 'async' is True, the generator is returned to the caller, 
        # otherwise it is executed to completion here.                        
        if async:
            return handshaker
        for result in handshaker:
            pass


    def _handshakeClientAsync(self, srpParams=(), certParams=(), anonParams=(),
                             session=None, settings=None, checker=None,
                             nextProtos=None, serverName="", reqTack=True):

        handshaker = self._handshakeClientAsyncHelper(srpParams=srpParams,
                certParams=certParams,
                anonParams=anonParams,
                session=session,
                settings=settings,
                serverName=serverName,
                nextProtos=nextProtos,
                reqTack=reqTack)
        for result in self._handshakeWrapperAsync(handshaker, checker):
            yield result


    def _handshakeClientAsyncHelper(self, srpParams, certParams, anonParams,
                               session, settings, serverName, nextProtos, reqTack):
        
        self._handshakeStart(client=True)

        #Unpack parameters
        srpUsername = None      # srpParams[0]
        password = None         # srpParams[1]
        clientCertChain = None  # certParams[0]
        privateKey = None       # certParams[1]

        # Allow only one of (srpParams, certParams, anonParams)
        if srpParams:
            assert(not certParams)
            assert(not anonParams)
            srpUsername, password = srpParams
        if certParams:
            assert(not srpParams)
            assert(not anonParams)            
            clientCertChain, privateKey = certParams
        if anonParams:
            assert(not srpParams)         
            assert(not certParams)

        #Validate parameters
        if srpUsername and not password:
            raise ValueError("Caller passed a username but no password")
        if password and not srpUsername:
            raise ValueError("Caller passed a password but no username")
        if clientCertChain and not privateKey:
            raise ValueError("Caller passed a certChain but no privateKey")
        if privateKey and not clientCertChain:
            raise ValueError("Caller passed a privateKey but no certChain")
        if reqTack:
            if not tackpyLoaded:
                reqTack = False
            if not settings or not settings.useExperimentalTackExtension:
                reqTack = False
        if nextProtos is not None:
            if len(nextProtos) == 0:
                raise ValueError("Caller passed no nextProtos")
        
        # Validates the settings and filters out any unsupported ciphers
        # or crypto libraries that were requested        
        if not settings:
            settings = HandshakeSettings()
        settings = settings._filter()

        if clientCertChain:
            if not isinstance(clientCertChain, X509CertChain):
                raise ValueError("Unrecognized certificate type")
            if "x509" not in settings.certificateTypes:
                raise ValueError("Client certificate doesn't match "\
                                 "Handshake Settings")
                                  
        if session:
            # session.valid() ensures session is resumable and has 
            # non-empty sessionID
            if not session.valid():
                session = None #ignore non-resumable sessions...
            elif session.resumable: 
                if session.srpUsername != srpUsername:
                    raise ValueError("Session username doesn't match")
                if session.serverName != serverName:
                    raise ValueError("Session servername doesn't match")

        #Add Faults to parameters
        if srpUsername and self.fault == Fault.badUsername:
            srpUsername += "GARBAGE"
        if password and self.fault == Fault.badPassword:
            password += "GARBAGE"

        #Tentatively set the version to the client's minimum version.
        #We'll use this for the ClientHello, and if an error occurs
        #parsing the Server Hello, we'll use this version for the response
        self.version = settings.maxVersion

        if settings.useEncryptThenMAC:
            extensions = [TLSExtension().create(ExtensionType.encrypt_then_mac,
                    bytearray(0))]
        else:
            extensions = None
        
        # OK Start sending messages!
        # *****************************

        # Send the ClientHello.
        for result in self._clientSendClientHello(settings, session, 
                                        srpUsername, srpParams, certParams,
                                        anonParams, serverName, nextProtos,
                                        reqTack, extensions=extensions):
            if result in (0,1): yield result
            else: break
        clientHello = result
        
        #Get the ServerHello.
        for result in self._clientGetServerHello(settings, clientHello):
            if result in (0,1): yield result
            else: break
        serverHello = result
        cipherSuite = serverHello.cipher_suite
        
        # Choose a matching Next Protocol from server list against ours
        # (string or None)
        nextProto = self._clientSelectNextProto(nextProtos, serverHello)

        # check if server supports encrypt_then_mac
        if serverHello.getExtension(ExtensionType.encrypt_then_mac):
            self.etm = True

        #If the server elected to resume the session, it is handled here.
        for result in self._clientResume(session, serverHello, 
                        clientHello.random, 
                        settings.cipherImplementations,
                        nextProto):
            if result in (0,1): yield result
            else: break
        if result == "resumed_and_finished":
            self.resumed = True
            self.closed = False
            return

        #If the server selected an SRP ciphersuite, the client finishes
        #reading the post-ServerHello messages, then derives a
        #premasterSecret and sends a corresponding ClientKeyExchange.
        if cipherSuite in CipherSuite.srpAllSuites:
            for result in self._clientSRPKeyExchange(\
                    settings, cipherSuite, serverHello.certificate_type, 
                    srpUsername, password,
                    clientHello.random, serverHello.random, 
                    serverHello.tackExt):                
                if result in (0,1): yield result
                else: break                
            (premasterSecret, serverCertChain, tackExt) = result

        #If the server selected an anonymous ciphersuite, the client
        #finishes reading the post-ServerHello messages.
        elif cipherSuite in CipherSuite.anonSuites:
            for result in self._clientAnonKeyExchange(settings, cipherSuite,
                                    clientHello.random, serverHello.random):
                if result in (0,1): yield result
                else: break
            (premasterSecret, serverCertChain, tackExt) = result     
               
        #If the server selected a certificate-based RSA ciphersuite,
        #the client finishes reading the post-ServerHello messages. If 
        #a CertificateRequest message was sent, the client responds with
        #a Certificate message containing its certificate chain (if any),
        #and also produces a CertificateVerify message that signs the 
        #ClientKeyExchange.
        else:
            for result in self._clientRSAKeyExchange(settings, cipherSuite,
                                    clientCertChain, privateKey,
                                    serverHello.certificate_type,
                                    clientHello.random, serverHello.random,
                                    serverHello.tackExt):
                if result in (0,1): yield result
                else: break
            (premasterSecret, serverCertChain, clientCertChain, 
             tackExt) = result
                        
        #After having previously sent a ClientKeyExchange, the client now
        #initiates an exchange of Finished messages.
        for result in self._clientFinished(premasterSecret,
                            clientHello.random, 
                            serverHello.random,
                            cipherSuite, settings.cipherImplementations,
                            nextProto):
                if result in (0,1): yield result
                else: break
        masterSecret = result
        
        # Create the session object which is used for resumptions
        self.session = Session()
        self.session.create(masterSecret, serverHello.session_id, cipherSuite,
            srpUsername, clientCertChain, serverCertChain,
            tackExt, serverHello.tackExt!=None, serverName)
        self.resumed = False
        self.closed = False


    def _clientSendClientHello(self, settings, session, srpUsername,
                                srpParams, certParams, anonParams, 
                                serverName, nextProtos, reqTack,
                                extensions=None):
        #Initialize acceptable ciphersuites
        cipherSuites = [CipherSuite.TLS_EMPTY_RENEGOTIATION_INFO_SCSV]
        if srpParams:
            cipherSuites += CipherSuite.getSrpAllSuites(settings)
        elif certParams:
            cipherSuites += CipherSuite.getCertSuites(settings)
        elif anonParams:
            cipherSuites += CipherSuite.getAnonSuites(settings)
        else:
            assert(False)

        #Initialize acceptable certificate types
        certificateTypes = settings._getCertificateTypes()
            
        #Either send ClientHello (with a resumable session)...
        if session and session.sessionID:
            #If it's resumable, then its
            #ciphersuite must be one of the acceptable ciphersuites
            if session.cipherSuite not in cipherSuites:
                raise ValueError("Session's cipher suite not consistent "\
                                 "with parameters")
            else:
                clientHello = ClientHello()
                clientHello.create(settings.maxVersion, getRandomBytes(32),
                                   session.sessionID, cipherSuites,
                                   certificateTypes, 
                                   session.srpUsername,
                                   reqTack, nextProtos is not None,
                                   session.serverName,
                                   extensions=extensions)

        #Or send ClientHello (without)
        else:
            clientHello = ClientHello()
            clientHello.create(settings.maxVersion, getRandomBytes(32),
                               bytearray(0), cipherSuites,
                               certificateTypes, 
                               srpUsername,
                               reqTack, nextProtos is not None, 
                               serverName,
                               extensions=extensions)
        for result in self.sendMessage(clientHello):
            yield result
        yield clientHello


    def _clientGetServerHello(self, settings, clientHello):
        for result in self._getMsg(ContentType.handshake,
                                  HandshakeType.server_hello):
            if result in (0,1): yield result
            else: break
        serverHello = result

        #Get the server version.  Do this before anything else, so any
        #error alerts will use the server's version
        self.version = serverHello.server_version

        #Future responses from server must use this version
        self._versionCheck = True

        verifier = ServerHelloVerifier(clientHello, settings)
        try:
            verifier.verify(serverHello)
        except TLSIllegalParameterException as e:
            for result in self._sendError(\
                    AlertDescription.illegal_parameter,
                    str(e)):
                yield result
        except TLSProtocolVersionException as e:
            for result in self._sendError(\
                    AlertDescription.protocol_version,
                    str(e)):
                yield result

        #Check ServerHello
        if serverHello.tackExt:            
            if not serverHello.tackExt.verifySignatures():
                for result in self._sendError(\
                    AlertDescription.decrypt_error,
                    "TackExtension contains an invalid signature"):
                    yield result
        yield serverHello

    def _clientSelectNextProto(self, nextProtos, serverHello):
        # nextProtos is None or non-empty list of strings
        # serverHello.next_protos is None or possibly-empty list of strings
        #
        # !!! We assume the client may have specified nextProtos as a list of
        # strings so we convert them to bytearrays (it's awkward to require
        # the user to specify a list of bytearrays or "bytes", and in 
        # Python 2.6 bytes() is just an alias for str() anyways...
        if nextProtos is not None and serverHello.next_protos is not None:
            for p in nextProtos:
                if bytearray(p) in serverHello.next_protos:
                    return bytearray(p)
            else:
                # If the client doesn't support any of server's protocols,
                # or the server doesn't advertise any (next_protos == [])
                # the client SHOULD select the first protocol it supports.
                return bytearray(nextProtos[0])
        return None
 
    def _clientResume(self, session, serverHello, clientRandom, 
                      cipherImplementations, nextProto):
        #If the server agrees to resume
        if session and session.sessionID and \
            serverHello.session_id == session.sessionID:

            if serverHello.cipher_suite != session.cipherSuite:
                for result in self._sendError(\
                    AlertDescription.illegal_parameter,\
                    "Server's ciphersuite doesn't match session"):
                    yield result

            #Calculate pending connection states
            self.calcPendingStates(session.cipherSuite,
                                    session.masterSecret, 
                                    clientRandom, serverHello.random, 
                                    cipherImplementations)                                   

            #Exchange ChangeCipherSpec and Finished messages
            for result in self._getFinished(session.masterSecret):
                yield result
            for result in self._sendFinished(session.masterSecret, nextProto):
                yield result

            #Set the session for this connection
            self.session = session
            yield "resumed_and_finished"        
            
    def _clientSRPKeyExchange(self, settings, cipherSuite, certificateType, 
            srpUsername, password,
            clientRandom, serverRandom, tackExt):

        #If the server chose an SRP+RSA suite...
        if cipherSuite in CipherSuite.srpCertSuites:
            #Get Certificate, ServerKeyExchange, ServerHelloDone
            for result in self._getMsg(ContentType.handshake,
                    HandshakeType.certificate, certificateType):
                if result in (0,1): yield result
                else: break
            serverCertificate = result
        else:
            serverCertificate = None

        for result in self._getMsg(ContentType.handshake,
                HandshakeType.server_key_exchange, cipherSuite):
            if result in (0,1): yield result
            else: break
        serverKeyExchange = result

        for result in self._getMsg(ContentType.handshake,
                HandshakeType.server_hello_done):
            if result in (0,1): yield result
            else: break
        serverHelloDone = result
            
        #Calculate SRP premaster secret
        #Get and check the server's group parameters and B value
        N = serverKeyExchange.srp_N
        g = serverKeyExchange.srp_g
        s = serverKeyExchange.srp_s
        B = serverKeyExchange.srp_B

        if (g,N) not in goodGroupParameters:
            for result in self._sendError(\
                    AlertDescription.insufficient_security,
                    "Unknown group parameters"):
                yield result
        if numBits(N) < settings.minKeySize:
            for result in self._sendError(\
                    AlertDescription.insufficient_security,
                    "N value is too small: %d" % numBits(N)):
                yield result
        if numBits(N) > settings.maxKeySize:
            for result in self._sendError(\
                    AlertDescription.insufficient_security,
                    "N value is too large: %d" % numBits(N)):
                yield result
        if B % N == 0:
            for result in self._sendError(\
                    AlertDescription.illegal_parameter,
                    "Suspicious B value"):
                yield result

        #Check the server's signature, if server chose an
        #SRP+RSA suite
        serverCertChain = None
        if cipherSuite in CipherSuite.srpCertSuites:
            #Hash ServerKeyExchange/ServerSRPParams
            hashBytes = serverKeyExchange.hash(clientRandom, serverRandom)

            #Extract signature bytes from ServerKeyExchange
            sigBytes = serverKeyExchange.signature
            if len(sigBytes) == 0:
                for result in self._sendError(\
                        AlertDescription.illegal_parameter,
                        "Server sent an SRP ServerKeyExchange "\
                        "message without a signature"):
                    yield result

            # Get server's public key from the Certificate message
            # Also validate the chain against the ServerHello's TACKext (if any)
            # If none, and a TACK cert is present, return its TACKext  
            for result in self._clientGetKeyFromChain(serverCertificate,
                                               settings, tackExt):
                if result in (0,1): yield result
                else: break
            publicKey, serverCertChain, tackExt = result

            #Verify signature
            if not publicKey.verify(sigBytes, hashBytes):
                for result in self._sendError(\
                        AlertDescription.decrypt_error,
                        "Signature failed to verify"):
                    yield result

        #Calculate client's ephemeral DH values (a, A)
        a = bytesToNumber(getRandomBytes(32))
        A = powMod(g, a, N)

        #Calculate client's static DH values (x, v)
        x = makeX(s, bytearray(srpUsername, "utf-8"),
                    bytearray(password, "utf-8"))
        v = powMod(g, x, N)

        #Calculate u
        u = makeU(N, A, B)

        #Calculate premaster secret
        k = makeK(N, g)
        S = powMod((B - (k*v)) % N, a+(u*x), N)

        if self.fault == Fault.badA:
            A = N
            S = 0
            
        premasterSecret = numberToByteArray(S)

        #Send ClientKeyExchange
        for result in self.sendMessage(\
                ClientKeyExchange(cipherSuite).createSRP(A)):
            yield result
        yield (premasterSecret, serverCertChain, tackExt)
                   

    def _clientRSAKeyExchange(self, settings, cipherSuite, 
                                clientCertChain, privateKey,
                                certificateType,
                                clientRandom, serverRandom,
                                tackExt):

        #Get Certificate[, CertificateRequest], ServerHelloDone
        for result in self._getMsg(ContentType.handshake,
                HandshakeType.certificate, certificateType):
            if result in (0,1): yield result
            else: break
        serverCertificate = result

        # Get CertificateRequest or ServerHelloDone
        for result in self._getMsg(ContentType.handshake,
                (HandshakeType.server_hello_done,
                HandshakeType.certificate_request)):
            if result in (0,1): yield result
            else: break
        msg = result
        certificateRequest = None
        if isinstance(msg, CertificateRequest):
            certificateRequest = msg
            # We got CertificateRequest, so this must be ServerHelloDone
            for result in self._getMsg(ContentType.handshake,
                    HandshakeType.server_hello_done):
                if result in (0,1): yield result
                else: break
            serverHelloDone = result
        elif isinstance(msg, ServerHelloDone):
            serverHelloDone = msg

        # Get server's public key from the Certificate message
        # Also validate the chain against the ServerHello's TACKext (if any)
        # If none, and a TACK cert is present, return its TACKext  
        for result in self._clientGetKeyFromChain(serverCertificate,
                                           settings, tackExt):
            if result in (0,1): yield result
            else: break
        publicKey, serverCertChain, tackExt = result

        #Calculate premaster secret
        premasterSecret = getRandomBytes(48)
        premasterSecret[0] = settings.maxVersion[0]
        premasterSecret[1] = settings.maxVersion[1]

        if self.fault == Fault.badPremasterPadding:
            premasterSecret[0] = 5
        if self.fault == Fault.shortPremasterSecret:
            premasterSecret = premasterSecret[:-1]

        #Encrypt premaster secret to server's public key
        encryptedPreMasterSecret = publicKey.encrypt(premasterSecret)

        #If client authentication was requested, send Certificate
        #message, either with certificates or empty
        if certificateRequest:
            clientCertificate = Certificate(certificateType)

            if clientCertChain:
                #Check to make sure we have the same type of
                #certificates the server requested
                wrongType = False
                if certificateType == CertificateType.x509:
                    if not isinstance(clientCertChain, X509CertChain):
                        wrongType = True
                if wrongType:
                    for result in self._sendError(\
                            AlertDescription.handshake_failure,
                            "Client certificate is of wrong type"):
                        yield result

                clientCertificate.create(clientCertChain)
            for result in self.sendMessage(clientCertificate):
                yield result
        else:
            #The server didn't request client auth, so we
            #zeroize these so the clientCertChain won't be
            #stored in the session.
            privateKey = None
            clientCertChain = None

        #Send ClientKeyExchange
        clientKeyExchange = ClientKeyExchange(cipherSuite,
                                              self.version)
        clientKeyExchange.createRSA(encryptedPreMasterSecret)
        for result in self.sendMessage(clientKeyExchange):
            yield result

        #If client authentication was requested and we have a
        #private key, send CertificateVerify
        if certificateRequest and privateKey:
            if self.version == (3,0):
                masterSecret = calcMasterSecret(self.version,
                                         premasterSecret,
                                         clientRandom,
                                         serverRandom)
                verifyBytes = self._handshakeHashes.digestSSL(masterSecret, b'')
            else:
                verifyBytes = self._handshakeHashes.digest(self.version)
            if self.fault == Fault.badVerifyMessage:
                verifyBytes[0] = ((verifyBytes[0]+1) % 256)
            signedBytes = privateKey.sign(verifyBytes)
            certificateVerify = CertificateVerify()
            certificateVerify.create(signedBytes)
            for result in self.sendMessage(certificateVerify):
                yield result
        yield (premasterSecret, serverCertChain, clientCertChain, tackExt)

    def _clientAnonKeyExchange(self, settings, cipherSuite, clientRandom, 
                               serverRandom):
        for result in self._getMsg(ContentType.handshake,
                HandshakeType.server_key_exchange, cipherSuite):
            if result in (0,1): yield result
            else: break
        serverKeyExchange = result

        for result in self._getMsg(ContentType.handshake,
                HandshakeType.server_hello_done):
            if result in (0,1): yield result
            else: break
        serverHelloDone = result
            
        #calculate Yc
        dh_p = serverKeyExchange.dh_p
        dh_g = serverKeyExchange.dh_g
        dh_Xc = bytesToNumber(getRandomBytes(32))
        dh_Ys = serverKeyExchange.dh_Ys
        dh_Yc = powMod(dh_g, dh_Xc, dh_p)
        
        #Send ClientKeyExchange
        for result in self.sendMessage(\
                ClientKeyExchange(cipherSuite, self.version).createDH(dh_Yc)):
            yield result
            
        #Calculate premaster secret
        S = powMod(dh_Ys, dh_Xc, dh_p)
        premasterSecret = numberToByteArray(S)
                     
        yield (premasterSecret, None, None)
        
    def _clientFinished(self, premasterSecret, clientRandom, serverRandom,
                        cipherSuite, cipherImplementations, nextProto):

        masterSecret = calcMasterSecret(self.version, premasterSecret,
                            clientRandom, serverRandom)
        self.calcPendingStates(cipherSuite, masterSecret,
                                clientRandom, serverRandom, 
                                cipherImplementations)

        #Exchange ChangeCipherSpec and Finished messages
        for result in self._sendFinished(masterSecret, nextProto):
            yield result
        for result in self._getFinished(masterSecret, nextProto=nextProto):
            yield result
        yield masterSecret

    def _clientGetKeyFromChain(self, certificate, settings, tackExt=None):
        #Get and check cert chain from the Certificate message
        certChain = certificate.certChain
        if not certChain or certChain.getNumCerts() == 0:
            for result in self._sendError(AlertDescription.illegal_parameter,
                    "Other party sent a Certificate message without "\
                    "certificates"):
                yield result

        #Get and check public key from the cert chain
        publicKey = certChain.getEndEntityPublicKey()
        if len(publicKey) < settings.minKeySize:
            for result in self._sendError(AlertDescription.handshake_failure,
                    "Other party's public key too small: %d" % len(publicKey)):
                yield result
        if len(publicKey) > settings.maxKeySize:
            for result in self._sendError(AlertDescription.handshake_failure,
                    "Other party's public key too large: %d" % len(publicKey)):
                yield result
        
        # If there's no TLS Extension, look for a TACK cert
        if tackpyLoaded:
            if not tackExt:
                tackExt = certChain.getTackExt()
         
            # If there's a TACK (whether via TLS or TACK Cert), check that it
            # matches the cert chain   
            if tackExt and tackExt.tacks:
                for tack in tackExt.tacks: 
                    if not certChain.checkTack(tack):
                        for result in self._sendError(  
                                AlertDescription.illegal_parameter,
                                "Other party's TACK doesn't match their public key"):
                                yield result

        yield publicKey, certChain, tackExt


    #*********************************************************
    # Server Handshake Functions
    #*********************************************************


    def handshakeServer(self, verifierDB=None,
                        certChain=None, privateKey=None, reqCert=False,
                        sessionCache=None, settings=None, checker=None,
                        reqCAs = None, 
                        tacks=None, activationFlags=0,
                        nextProtos=None, anon=False):
        """Perform a handshake in the role of server.

        This function performs an SSL or TLS handshake.  Depending on
        the arguments and the behavior of the client, this function can
        perform an SRP, or certificate-based handshake.  It
        can also perform a combined SRP and server-certificate
        handshake.

        Like any handshake function, this can be called on a closed
        TLS connection, or on a TLS connection that is already open.
        If called on an open connection it performs a re-handshake.
        This function does not send a Hello Request message before
        performing the handshake, so if re-handshaking is required,
        the server must signal the client to begin the re-handshake
        through some other means.

        If the function completes without raising an exception, the
        TLS connection will be open and available for data transfer.

        If an exception is raised, the connection will have been
        automatically closed (if it was ever open).

        @type verifierDB: L{tlslite.verifierdb.VerifierDB}
        @param verifierDB: A database of SRP password verifiers
        associated with usernames.  If the client performs an SRP
        handshake, the session's srpUsername attribute will be set.

        @type certChain: L{tlslite.x509certchain.X509CertChain}
        @param certChain: The certificate chain to be used if the
        client requests server certificate authentication.

        @type privateKey: L{tlslite.utils.rsakey.RSAKey}
        @param privateKey: The private key to be used if the client
        requests server certificate authentication.

        @type reqCert: bool
        @param reqCert: Whether to request client certificate
        authentication.  This only applies if the client chooses server
        certificate authentication; if the client chooses SRP
        authentication, this will be ignored.  If the client
        performs a client certificate authentication, the sessions's
        clientCertChain attribute will be set.

        @type sessionCache: L{tlslite.sessioncache.SessionCache}
        @param sessionCache: An in-memory cache of resumable sessions.
        The client can resume sessions from this cache.  Alternatively,
        if the client performs a full handshake, a new session will be
        added to the cache.

        @type settings: L{tlslite.handshakesettings.HandshakeSettings}
        @param settings: Various settings which can be used to control
        the ciphersuites and SSL/TLS version chosen by the server.

        @type checker: L{tlslite.checker.Checker}
        @param checker: A Checker instance.  This instance will be
        invoked to examine the other party's authentication
        credentials, if the handshake completes succesfully.
        
        @type reqCAs: list of L{bytearray} of unsigned bytes
        @param reqCAs: A collection of DER-encoded DistinguishedNames that
        will be sent along with a certificate request. This does not affect
        verification.        

        @type nextProtos: list of strings.
        @param nextProtos: A list of upper layer protocols to expose to the
        clients through the Next-Protocol Negotiation Extension, 
        if they support it.

        @raise socket.error: If a socket error occurs.
        @raise tlslite.errors.TLSAbruptCloseError: If the socket is closed
        without a preceding alert.
        @raise tlslite.errors.TLSAlert: If a TLS alert is signalled.
        @raise tlslite.errors.TLSAuthenticationError: If the checker
        doesn't like the other party's authentication credentials.
        """
        for result in self.handshakeServerAsync(verifierDB,
                certChain, privateKey, reqCert, sessionCache, settings,
                checker, reqCAs, 
                tacks=tacks, activationFlags=activationFlags, 
                nextProtos=nextProtos, anon=anon):
            pass


    def handshakeServerAsync(self, verifierDB=None,
                             certChain=None, privateKey=None, reqCert=False,
                             sessionCache=None, settings=None, checker=None,
                             reqCAs=None, 
                             tacks=None, activationFlags=0,
                             nextProtos=None, anon=False
                             ):
        """Start a server handshake operation on the TLS connection.

        This function returns a generator which behaves similarly to
        handshakeServer().  Successive invocations of the generator
        will return 0 if it is waiting to read from the socket, 1 if it is
        waiting to write to the socket, or it will raise StopIteration
        if the handshake operation is complete.

        @rtype: iterable
        @return: A generator; see above for details.
        """
        handshaker = self._handshakeServerAsyncHelper(\
            verifierDB=verifierDB, certChain=certChain,
            privateKey=privateKey, reqCert=reqCert,
            sessionCache=sessionCache, settings=settings, 
            reqCAs=reqCAs, 
            tacks=tacks, activationFlags=activationFlags, 
            nextProtos=nextProtos, anon=anon)
        for result in self._handshakeWrapperAsync(handshaker, checker):
            yield result


    def _handshakeServerAsyncHelper(self, verifierDB,
                             certChain, privateKey, reqCert, sessionCache,
                             settings, reqCAs, 
                             tacks, activationFlags, 
                             nextProtos, anon):

        self._handshakeStart(client=False)

        if (not verifierDB) and (not certChain) and not anon:
            raise ValueError("Caller passed no authentication credentials")
        if certChain and not privateKey:
            raise ValueError("Caller passed a certChain but no privateKey")
        if privateKey and not certChain:
            raise ValueError("Caller passed a privateKey but no certChain")
        if reqCAs and not reqCert:
            raise ValueError("Caller passed reqCAs but not reqCert")            
        if certChain and not isinstance(certChain, X509CertChain):
            raise ValueError("Unrecognized certificate type")
        if activationFlags and not tacks:
            raise ValueError("Nonzero activationFlags requires tacks")
        if tacks:
            if not tackpyLoaded:
                raise ValueError("tackpy is not loaded")
            if not settings or not settings.useExperimentalTackExtension:
                raise ValueError("useExperimentalTackExtension not enabled")

        if not settings:
            settings = HandshakeSettings()
        settings = settings._filter()
        
        # OK Start exchanging messages
        # ******************************
        
        # Handle ClientHello and resumption
        for result in self._serverGetClientHello(settings, certChain,\
                                            verifierDB, sessionCache,
                                            anon):
            if result in (0,1): yield result
            elif result == None:
                self.resumed = True
                self.closed = False
                return # Handshake was resumed, we're done 
            else: break
        (clientHello, cipherSuite) = result
        
        #If not a resumption...

        # Create the ServerHello message
        if sessionCache:
            sessionID = getRandomBytes(32)
        else:
            sessionID = bytearray(0)
        
        if not clientHello.supports_npn:
            nextProtos = None

        # If not doing a certificate-based suite, discard the TACK
        if not cipherSuite in CipherSuite.certAllSuites:
            tacks = None

        # Prepare a TACK Extension if requested
        if clientHello.tack:
            tackExt = TackExtension.create(tacks, activationFlags)
        else:
            tackExt = None

        # prepare encrypt then mac if required
        if settings.useEncryptThenMAC and\
                clientHello.getExtension(ExtensionType.encrypt_then_mac) and\
                not cipherSuite in [CipherSuite.TLS_RSA_WITH_RC4_128_SHA,\
                CipherSuite.TLS_RSA_WITH_RC4_128_MD5]:
            extensions = [TLSExtension().create(
                    ExtensionType.encrypt_then_mac,
                    bytearray(0))]
            self.etm = True
        else:
            extensions = None

        serverHello = ServerHello()
        serverHello.create(self.version, getRandomBytes(32), sessionID, \
                            cipherSuite, CertificateType.x509, tackExt,
                            nextProtos, extensions=extensions)

        # Perform the SRP key exchange
        clientCertChain = None
        if cipherSuite in CipherSuite.srpAllSuites:
            for result in self._serverSRPKeyExchange(clientHello, serverHello, 
                                    verifierDB, cipherSuite, 
                                    privateKey, certChain):
                if result in (0,1): yield result
                else: break
            premasterSecret = result

        # Perform the RSA key exchange
        elif cipherSuite in CipherSuite.certSuites:
            for result in self._serverCertKeyExchange(clientHello, serverHello, 
                                        certChain, privateKey,
                                        reqCert, reqCAs, cipherSuite,
                                        settings):
                if result in (0,1): yield result
                else: break
            (premasterSecret, clientCertChain) = result

        # Perform anonymous Diffie Hellman key exchange
        elif cipherSuite in CipherSuite.anonSuites:
            for result in self._serverAnonKeyExchange(clientHello, serverHello, 
                                        cipherSuite, settings):
                if result in (0,1): yield result
                else: break
            premasterSecret = result
        
        else:
            assert(False)
                        
        # Exchange Finished messages      
        for result in self._serverFinished(premasterSecret, 
                                clientHello.random, serverHello.random,
                                cipherSuite, settings.cipherImplementations,
                                nextProtos):
                if result in (0,1): yield result
                else: break
        masterSecret = result

        #Create the session object
        self.session = Session()
        if cipherSuite in CipherSuite.certAllSuites:        
            serverCertChain = certChain
        else:
            serverCertChain = None
        srpUsername = None
        serverName = None
        if clientHello.srp_username:
            srpUsername = clientHello.srp_username.decode("utf-8")
        if clientHello.server_name:
            serverName = clientHello.server_name.decode("utf-8")
        self.session.create(masterSecret, serverHello.session_id, cipherSuite,
            srpUsername, clientCertChain, serverCertChain,
            tackExt, serverHello.tackExt!=None, serverName)
            
        #Add the session object to the session cache
        if sessionCache and sessionID:
            sessionCache[sessionID] = self.session

        self.resumed = False
        self.closed = False


    def _serverGetClientHello(self, settings, certChain, verifierDB,
                                sessionCache, anon):
        #Initialize acceptable cipher suites
        cipherSuites = []
        if verifierDB:
            if certChain:
                cipherSuites += \
                    CipherSuite.getSrpCertSuites(settings)
            cipherSuites += CipherSuite.getSrpSuites(settings)
        elif certChain:
            cipherSuites += CipherSuite.getCertSuites(settings)
        elif anon:
            cipherSuites += CipherSuite.getAnonSuites(settings)
        else:
            assert(False)

        #Tentatively set version to most-desirable version, so if an error
        #occurs parsing the ClientHello, this is what we'll use for the
        #error alert
        self.version = settings.maxVersion

        #Get ClientHello
        for result in self._getMsg(ContentType.handshake,
                                   HandshakeType.client_hello):
            if result in (0,1): yield result
            else: break
        clientHello = result

        #If client's version is too low, reject it
        if clientHello.client_version < settings.minVersion:
            self.version = settings.minVersion
            for result in self._sendError(\
                  AlertDescription.protocol_version,
                  "Too old version: %s" % str(clientHello.client_version)):
                yield result

        #If client's version is too high, propose my highest version
        elif clientHello.client_version > settings.maxVersion:
            self.version = settings.maxVersion

        else:
            #Set the version to the client's version
            self.version = clientHello.client_version  

        #If resumption was requested and we have a session cache...
        if clientHello.session_id and sessionCache:
            session = None

            #Check in the session cache
            if sessionCache and not session:
                try:
                    session = sessionCache[clientHello.session_id]
                    if not session.resumable:
                        raise AssertionError()
                    #Check for consistency with ClientHello
                    if session.cipherSuite not in cipherSuites:
                        for result in self._sendError(\
                                AlertDescription.handshake_failure):
                            yield result
                    if session.cipherSuite not in clientHello.cipher_suites:
                        for result in self._sendError(\
                                AlertDescription.handshake_failure):
                            yield result
                    if clientHello.srp_username:
                        if not session.srpUsername or \
                            clientHello.srp_username != bytearray(session.srpUsername, "utf-8"):
                            for result in self._sendError(\
                                    AlertDescription.handshake_failure):
                                yield result
                    if clientHello.server_name:
                        if not session.serverName or \
                            clientHello.server_name != bytearray(session.serverName, "utf-8"):
                            for result in self._sendError(\
                                    AlertDescription.handshake_failure):
                                yield result                    
                except KeyError:
                    pass

            #If a session is found..
            if session:
                #Send ServerHello
                serverHello = ServerHello()
                serverHello.create(self.version, getRandomBytes(32),
                                   session.sessionID, session.cipherSuite,
                                   CertificateType.x509, None, None)
                for result in self.sendMessage(serverHello):
                    yield result

                #From here on, the client's messages must have right version
                self._versionCheck = True

                #Calculate pending connection states
                self.calcPendingStates(session.cipherSuite,
                                        session.masterSecret,
                                        clientHello.random, 
                                        serverHello.random,
                                        settings.cipherImplementations)

                #Exchange ChangeCipherSpec and Finished messages
                for result in self._sendFinished(session.masterSecret):
                    yield result
                for result in self._getFinished(session.masterSecret):
                    yield result

                #Set the session
                self.session = session
                    
                yield None # Handshake done!

        #Calculate the first cipher suite intersection.
        #This is the 'privileged' ciphersuite.  We'll use it if we're
        #doing a new negotiation.  In fact,
        #the only time we won't use it is if we're resuming a
        #session, in which case we use the ciphersuite from the session.
        #
        #Given the current ciphersuite ordering, this means we prefer SRP
        #over non-SRP.
        for cipherSuite in cipherSuites:
            if cipherSuite in clientHello.cipher_suites:
                break
        else:
            for result in self._sendError(\
                    AlertDescription.handshake_failure,
                    "No mutual ciphersuite"):
                yield result
        if cipherSuite in CipherSuite.srpAllSuites and \
                            not clientHello.srp_username:
            for result in self._sendError(\
                    AlertDescription.unknown_psk_identity,
                    "Client sent a hello, but without the SRP username"):
                yield result
           
        #If an RSA suite is chosen, check for certificate type intersection
        if cipherSuite in CipherSuite.certAllSuites and CertificateType.x509 \
                                not in clientHello.certificate_types:
            for result in self._sendError(\
                    AlertDescription.handshake_failure,
                    "the client doesn't support my certificate type"):
                yield result

        # If resumption was not requested, or
        # we have no session cache, or
        # the client's session_id was not found in cache:
        yield (clientHello, cipherSuite)

    def _serverSRPKeyExchange(self, clientHello, serverHello, verifierDB, 
                                cipherSuite, privateKey, serverCertChain):

        srpUsername = clientHello.srp_username.decode("utf-8")
        self.allegedSrpUsername = srpUsername
        #Get parameters from username
        try:
            entry = verifierDB[srpUsername]
        except KeyError:
            for result in self._sendError(\
                    AlertDescription.unknown_psk_identity):
                yield result
        (N, g, s, v) = entry

        #Calculate server's ephemeral DH values (b, B)
        b = bytesToNumber(getRandomBytes(32))
        k = makeK(N, g)
        B = (powMod(g, b, N) + (k*v)) % N

        #Create ServerKeyExchange, signing it if necessary
        serverKeyExchange = ServerKeyExchange(cipherSuite)
        serverKeyExchange.createSRP(N, g, s, B)
        if cipherSuite in CipherSuite.srpCertSuites:
            hashBytes = serverKeyExchange.hash(clientHello.random,
                                               serverHello.random)
            serverKeyExchange.signature = privateKey.sign(hashBytes)

        #Send ServerHello[, Certificate], ServerKeyExchange,
        #ServerHelloDone
        msgs = []
        msgs.append(serverHello)
        if cipherSuite in CipherSuite.srpCertSuites:
            certificateMsg = Certificate(CertificateType.x509)
            certificateMsg.create(serverCertChain)
            msgs.append(certificateMsg)
        msgs.append(serverKeyExchange)
        msgs.append(ServerHelloDone())
        for result in self.sendMessages(msgs):
            yield result

        #From here on, the client's messages must have the right version
        self._versionCheck = True

        #Get and check ClientKeyExchange
        for result in self._getMsg(ContentType.handshake,
                                  HandshakeType.client_key_exchange,
                                  cipherSuite):
            if result in (0,1): yield result
            else: break
        clientKeyExchange = result
        A = clientKeyExchange.srp_A
        if A % N == 0:
            for result in self._sendError(AlertDescription.illegal_parameter,
                    "Suspicious A value"):
                yield result
            assert(False) # Just to ensure we don't fall through somehow

        #Calculate u
        u = makeU(N, A, B)

        #Calculate premaster secret
        S = powMod((A * powMod(v,u,N)) % N, b, N)
        premasterSecret = numberToByteArray(S)
        
        yield premasterSecret


    def _serverCertKeyExchange(self, clientHello, serverHello, 
                                serverCertChain, privateKey,
                                reqCert, reqCAs, cipherSuite,
                                settings):
        #Send ServerHello, Certificate[, CertificateRequest],
        #ServerHelloDone
        msgs = []

        # If we verify a client cert chain, return it
        clientCertChain = None

        msgs.append(serverHello)
        msgs.append(Certificate(CertificateType.x509).create(serverCertChain))
        if reqCert and reqCAs:
            msgs.append(CertificateRequest().create(\
                [ClientCertificateType.rsa_sign], reqCAs))
        elif reqCert:
            msgs.append(CertificateRequest(self.version))
        msgs.append(ServerHelloDone())
        for result in self.sendMessages(msgs):
            yield result

        #From here on, the client's messages must have the right version
        self._versionCheck = True

        #Get [Certificate,] (if was requested)
        if reqCert:
            if self.version == (3,0):
                for result in self._getMsg((ContentType.handshake,
                                           ContentType.alert),
                                           HandshakeType.certificate,
                                           CertificateType.x509):
                    if result in (0,1): yield result
                    else: break
                msg = result

                if isinstance(msg, Alert):
                    #If it's not a no_certificate alert, re-raise
                    alert = msg
                    if alert.description != \
                            AlertDescription.no_certificate:
                        self._shutdown(False)
                        raise TLSRemoteAlert(alert)
                elif isinstance(msg, Certificate):
                    clientCertificate = msg
                    if clientCertificate.certChain and \
                            clientCertificate.certChain.getNumCerts()!=0:
                        clientCertChain = clientCertificate.certChain
                else:
                    raise AssertionError()
            elif self.version in ((3,1), (3,2), (3,3)):
                for result in self._getMsg(ContentType.handshake,
                                          HandshakeType.certificate,
                                          CertificateType.x509):
                    if result in (0,1): yield result
                    else: break
                clientCertificate = result
                if clientCertificate.certChain and \
                        clientCertificate.certChain.getNumCerts()!=0:
                    clientCertChain = clientCertificate.certChain
            else:
                raise AssertionError()

        #Get ClientKeyExchange
        for result in self._getMsg(ContentType.handshake,
                                  HandshakeType.client_key_exchange,
                                  cipherSuite):
            if result in (0,1): yield result
            else: break
        clientKeyExchange = result

        #Decrypt ClientKeyExchange
        premasterSecret = privateKey.decrypt(\
            clientKeyExchange.encryptedPreMasterSecret)

        # On decryption failure randomize premaster secret to avoid
        # Bleichenbacher's "million message" attack
        randomPreMasterSecret = getRandomBytes(48)
        versionCheck = (premasterSecret[0], premasterSecret[1])
        if not premasterSecret:
            premasterSecret = randomPreMasterSecret
        elif len(premasterSecret)!=48:
            premasterSecret = randomPreMasterSecret
        elif versionCheck != clientHello.client_version:
            if versionCheck != self.version: #Tolerate buggy IE clients
                premasterSecret = randomPreMasterSecret

        #Get and check CertificateVerify, if relevant
        if clientCertChain:
            if self.version == (3,0):
                masterSecret = calcMasterSecret(self.version, premasterSecret,
                                         clientHello.random, serverHello.random)
                verifyBytes = self._handshakeHashes.digestSSL(masterSecret, b'')
            else:
                verifyBytes = self._handshakeHashes.digest(self.version)
            for result in self._getMsg(ContentType.handshake,
                                      HandshakeType.certificate_verify):
                if result in (0,1): yield result
                else: break
            certificateVerify = result
            publicKey = clientCertChain.getEndEntityPublicKey()
            if len(publicKey) < settings.minKeySize:
                for result in self._sendError(\
                        AlertDescription.handshake_failure,
                        "Client's public key too small: %d" % len(publicKey)):
                    yield result

            if len(publicKey) > settings.maxKeySize:
                for result in self._sendError(\
                        AlertDescription.handshake_failure,
                        "Client's public key too large: %d" % len(publicKey)):
                    yield result

            if not publicKey.verify(certificateVerify.signature, verifyBytes):
                for result in self._sendError(\
                        AlertDescription.decrypt_error,
                        "Signature failed to verify"):
                    yield result
        yield (premasterSecret, clientCertChain)


    def _serverAnonKeyExchange(self, clientHello, serverHello, cipherSuite, 
                               settings):
        # Calculate DH p, g, Xs, Ys
        dh_p = getRandomSafePrime(32, False)
        dh_g = getRandomNumber(2, dh_p)        
        dh_Xs = bytesToNumber(getRandomBytes(32))        
        dh_Ys = powMod(dh_g, dh_Xs, dh_p)

        #Create ServerKeyExchange
        serverKeyExchange = ServerKeyExchange(cipherSuite)
        serverKeyExchange.createDH(dh_p, dh_g, dh_Ys)
        
        #Send ServerHello[, Certificate], ServerKeyExchange,
        #ServerHelloDone  
        msgs = []
        msgs.append(serverHello)
        msgs.append(serverKeyExchange)
        msgs.append(ServerHelloDone())
        for result in self.sendMessages(msgs):
            yield result
        
        #From here on, the client's messages must have the right version
        self._versionCheck = True
        
        #Get and check ClientKeyExchange
        for result in self._getMsg(ContentType.handshake,
                                   HandshakeType.client_key_exchange,
                                   cipherSuite):
            if result in (0,1):
                yield result 
            else:
                break
        clientKeyExchange = result
        dh_Yc = clientKeyExchange.dh_Yc
        
        if dh_Yc % dh_p == 0:
            for result in self._sendError(AlertDescription.illegal_parameter,
                    "Suspicious dh_Yc value"):
                yield result
            assert(False) # Just to ensure we don't fall through somehow            

        #Calculate premaster secre
        S = powMod(dh_Yc,dh_Xs,dh_p)
        premasterSecret = numberToByteArray(S)
        
        yield premasterSecret


    def _serverFinished(self,  premasterSecret, clientRandom, serverRandom,
                        cipherSuite, cipherImplementations, nextProtos):
        masterSecret = calcMasterSecret(self.version, premasterSecret,
                                      clientRandom, serverRandom)
        
        #Calculate pending connection states
        self.calcPendingStates(cipherSuite, masterSecret,
                                clientRandom, serverRandom,
                                cipherImplementations)

        #Exchange ChangeCipherSpec and Finished messages
        for result in self._getFinished(masterSecret, 
                        expect_next_protocol=nextProtos is not None):
            yield result

        for result in self._sendFinished(masterSecret):
            yield result
        
        yield masterSecret        


    #*********************************************************
    # Shared Handshake Functions
    #*********************************************************


    def _sendFinished(self, masterSecret, nextProto=None):
        #Send ChangeCipherSpec
        for result in self.sendMessage(ChangeCipherSpec()):
            yield result

        #Switch to pending write state
        self.changeWriteState()

        if nextProto is not None:
            nextProtoMsg = NextProtocol().create(nextProto)
            for result in self.sendMessage(nextProtoMsg):
                yield result

        #Calculate verification data
        verifyData = self._calcFinished(masterSecret, True)
        if self.fault == Fault.badFinished:
            verifyData[0] = (verifyData[0]+1)%256

        #Send Finished message under new state
        finished = Finished(self.version).create(verifyData)
        for result in self.sendMessage(finished):
            yield result

    def _getFinished(self, masterSecret, expect_next_protocol=False, nextProto=None):
        #Get and check ChangeCipherSpec
        for result in self._getMsg(ContentType.change_cipher_spec):
            if result in (0,1):
                yield result
        changeCipherSpec = result

        if changeCipherSpec.type != 1:
            for result in self._sendError(AlertDescription.illegal_parameter,
                                         "ChangeCipherSpec type incorrect"):
                yield result

        #Switch to pending read state
        self.changeReadState()

        #Server Finish - Are we waiting for a next protocol echo? 
        if expect_next_protocol:
            for result in self._getMsg(ContentType.handshake, HandshakeType.next_protocol):
                if result in (0,1):
                    yield result
            if result is None:
                for result in self._sendError(AlertDescription.unexpected_message,
                                             "Didn't get NextProtocol message"):
                    yield result

            self.next_proto = result.next_proto
        else:
            self.next_proto = None

        #Client Finish - Only set the next_protocol selected in the connection
        if nextProto:
            self.next_proto = nextProto

        #Calculate verification data
        verifyData = self._calcFinished(masterSecret, False)

        #Get and check Finished message under new state
        for result in self._getMsg(ContentType.handshake,
                                  HandshakeType.finished):
            if result in (0,1):
                yield result
        finished = result
        if finished.verify_data != verifyData:
            for result in self._sendError(AlertDescription.decrypt_error,
                                         "Finished message is incorrect"):
                yield result

    def _calcFinished(self, masterSecret, send=True):
        if self.version == (3,0):
            if (self.client and send) or (not self.client and not send):
                senderStr = b"\x43\x4C\x4E\x54"
            else:
                senderStr = b"\x53\x52\x56\x52"

            verifyData = self._handshakeHashes.digestSSL(masterSecret,
                    senderStr)
            return verifyData

        elif self.version in ((3,1), (3,2)):
            if (self.client and send) or (not self.client and not send):
                label = b"client finished"
            else:
                label = b"server finished"

            handshakeHashes = self._handshakeHashes.digest(self.version)
            verifyData = PRF(masterSecret, label, handshakeHashes, 12)
            return verifyData
        elif self.version == (3,3):
            if (self.client and send) or (not self.client and not send):
                label = b"client finished"
            else:
                label = b"server finished"

            handshakeHashes = self._handshakeHashes.digest(self.version)
            verifyData = PRF_1_2(masterSecret, label, handshakeHashes, 12)
            return verifyData
        else:
            raise AssertionError()


    def _handshakeWrapperAsync(self, handshaker, checker):
        if not self.fault:
            try:
                for result in handshaker:
                    yield result
                if checker:
                    try:
                        checker(self)
                    except TLSAuthenticationError:
                        alert = Alert().create(AlertDescription.close_notify,
                                               AlertLevel.fatal)
                        for result in self.sendMessage(alert):
                            yield result
                        raise
            except GeneratorExit:
                raise
            except TLSAlert as alert:
                if not self.fault:
                    raise
                if alert.description not in Fault.faultAlerts[self.fault]:
                    raise TLSFaultError(str(alert))
                else:
                    pass
            except:
                self._shutdown(False)
                raise


    def clearReadBuffer(self):
        """Clear the read buffer.

        Will drop all data read from last application data message as well as
        data that was "unread"
        """
        self._readBuffer = bytearray(0)

    def clearWriteBuffer(self):
        """Drop data in write buffer

        Currently a no-op, write* methods don't cache data
        """
        pass

    def read(self, max=None, min=1):
        """Read some data from the TLS connection.

        This function will block until at least 'min' bytes are
        available (or the connection is closed).

        If an exception is raised, the connection will have been
        automatically closed.

        @type max: int
        @param max: The maximum number of bytes to return.

        @type min: int
        @param min: The minimum number of bytes to return

        @rtype: str
        @return: A string of no more than 'max' bytes, and no fewer
        than 'min' (unless the connection has been closed, in which
        case fewer than 'min' bytes may be returned).

        @raise socket.error: If a socket error occurs.
        @raise tlslite.errors.TLSAbruptCloseError: If the socket is closed
        without a preceding alert.
        @raise tlslite.errors.TLSAlert: If a TLS alert is signalled.
        """
        for result in self.readAsync(max, min):
            pass
        return result

    def unread(self, b):
        """Add bytes to the front of the socket read buffer for future
        reading. Be careful using this in the context of select(...): if you
        unread the last data from a socket, that won't wake up selected waiters,
        and those waiters may hang forever.
        """
        self._readBuffer = b + self._readBuffer

    def write(self, s):
        """Write some data to the TLS connection.

        This function will block until all the data has been sent.

        If an exception is raised, the connection will have been
        automatically closed.

        @type s: str
        @param s: The data to transmit to the other party.

        @raise socket.error: If a socket error occurs.
        """
        for result in self.writeAsync(s):
            pass

    def readAsync(self, max=None, min=1):
        """Start a read operation on the TLS connection.

        This function returns a generator which behaves similarly to
        read().  Successive invocations of the generator will return 0
        if it is waiting to read from the socket, 1 if it is waiting
        to write to the socket, or a string if the read operation has
        completed.

        @rtype: iterable
        @return: A generator; see above for details.
        """
        try:
            while len(self._readBuffer)<min and not self.closed:
                try:
                    for result in self._getMsg(ContentType.application_data):
                        if result in (0,1):
                            yield result
                    applicationData = result
                    self._readBuffer += applicationData.write()
                except TLSRemoteAlert as alert:
                    if alert.description != AlertDescription.close_notify:
                        raise
                except TLSAbruptCloseError:
                    if not self.ignoreAbruptClose:
                        raise
                    else:
                        self._shutdown(True)

            if max == None:
                max = len(self._readBuffer)

            returnBytes = self._readBuffer[:max]
            self._readBuffer = self._readBuffer[max:]
            yield bytes(returnBytes)
        except GeneratorExit:
            raise
        except:
            self._shutdown(False)
            raise

    def writeAsync(self, s):
        """Start a write operation on the TLS connection.

        This function returns a generator which behaves similarly to
        write().  Successive invocations of the generator will return
        1 if it is waiting to write to the socket, or will raise
        StopIteration if the write operation has completed.

        @type s: bytearray
        @param s: application data bytes to send

        @rtype: iterable
        @return: A generator; see above for details.
        """
        try:
            if self.closed:
                raise TLSClosedConnectionError("attempt to write to closed connection")

            applicationData = ApplicationData().create(bytearray(s))
            for result in self.sendMessage(applicationData, \
                                        randomizeFirstBlock=True):
                yield result
        except GeneratorExit:
            raise
        except Exception:
            self._shutdown(False)
            raise

    def close(self):
        """Close the TLS connection.

        This function will block until it has exchanged close_notify
        alerts with the other party.  After doing so, it will shut down the
        TLS connection.  Further attempts to read through this connection
        will return "".  Further attempts to write through this connection
        will raise ValueError.

        If makefile() has been called on this connection, the connection
        will be not be closed until the connection object and all file
        objects have been closed.

        Even if an exception is raised, the connection will have been
        closed.

        @raise socket.error: If a socket error occurs.
        @raise tlslite.errors.TLSAbruptCloseError: If the socket is closed
        without a preceding alert.
        @raise tlslite.errors.TLSAlert: If a TLS alert is signalled.
        """
        if not self.closed:
            for result in self._decrefAsync():
                pass

    # Python 3 callback
    _decref_socketios = close

    def closeAsync(self):
        """Start a close operation on the TLS connection.

        This function returns a generator which behaves similarly to
        close().  Successive invocations of the generator will return 0
        if it is waiting to read from the socket, 1 if it is waiting
        to write to the socket, or will raise StopIteration if the
        close operation has completed.

        @rtype: iterable
        @return: A generator; see above for details.
        """
        if not self.closed:
            for result in self._decrefAsync():
                yield result

    def _decrefAsync(self):
        self._refCount -= 1
        if self._refCount == 0 and not self.closed:
            try:
                for result in self.sendMessage(Alert().create(\
                        AlertDescription.close_notify, AlertLevel.warning)):
                    yield result
                alert = None
                # By default close the socket, since it's been observed
                # that some other libraries will not respond to the
                # close_notify alert, thus leaving us hanging if we're
                # expecting it
                if self.closeSocket:
                    self._shutdown(True)
                else:
                    while not alert:
                        for result in self._getMsg((ContentType.alert, \
                                                  ContentType.application_data)):
                            if result in (0,1):
                                yield result
                        if result.contentType == ContentType.alert:
                            alert = result
                    if alert.description == AlertDescription.close_notify:
                        self._shutdown(True)
                    else:
                        raise TLSRemoteAlert(alert)
            except (socket.error, TLSAbruptCloseError):
                #If the other side closes the socket, that's okay
                self._shutdown(True)
            except GeneratorExit:
                raise
            except:
                self._shutdown(False)
                raise

    #Emulate a socket, somewhat -
    def send(self, s):
        """Send data to the TLS connection (socket emulation).

        @raise socket.error: If a socket error occurs.
        """
        self.write(s)
        return len(s)

    def sendall(self, s):
        """Send data to the TLS connection (socket emulation).

        @raise socket.error: If a socket error occurs.
        """
        self.write(s)

    def recv(self, bufsize):
        """Get some data from the TLS connection (socket emulation).

        @raise socket.error: If a socket error occurs.
        @raise tlslite.errors.TLSAbruptCloseError: If the socket is closed
        without a preceding alert.
        @raise tlslite.errors.TLSAlert: If a TLS alert is signalled.
        """
        return self.read(bufsize)

    def recv_into(self, b):
        # XXX doc string
        data = self.read(len(b))
        if not data:
            return None
        b[:len(data)] = data
        return len(data)

    def makefile(self, mode='r', bufsize=-1):
        """Create a file object for the TLS connection (socket emulation).

        @rtype: L{socket._fileobject}
        """
        self._refCount += 1
        # So, it is pretty fragile to be using Python internal objects
        # like this, but it is probably the best/easiest way to provide
        # matching behavior for socket emulation purposes.  The 'close'
        # argument is nice, its apparently a recent addition to this
        # class, so that when fileobject.close() gets called, it will
        # close() us, causing the refcount to be decremented (decrefAsync).
        #
        # If this is the last close() on the outstanding fileobjects /
        # TLSConnection, then the "actual" close alerts will be sent,
        # socket closed, etc.
        if sys.version_info < (3,):
            return socket._fileobject(self, mode, bufsize, close=True)
        else:
            # XXX need to wrap this further if buffering is requested
            return socket.SocketIO(self, mode)

    def getsockname(self):
        """Return the socket's own address (socket emulation)."""
        return self.sock.getsockname()

    def getpeername(self):
        """Return the remote address to which the socket is connected
        (socket emulation)."""
        return self.sock.getpeername()

    def settimeout(self, value):
        """Set a timeout on blocking socket operations (socket emulation)."""
        return self.sock.settimeout(value)

    def gettimeout(self):
        """Return the timeout associated with socket operations (socket
        emulation)."""
        return self.sock.gettimeout()

    def setsockopt(self, level, optname, value):
        """Set the value of the given socket option (socket emulation)."""
        return self.sock.setsockopt(level, optname, value)

    def shutdown(self, how):
        """Shutdown the underlying socket."""
        return self.sock.shutdown(how)

    def fileno(self):
        """Not implement in TLS Lite."""
        raise NotImplementedError()

    def sendMessage(self, msg, randomizeFirstBlock = True):
        # TODO: ignore handshake_request
        if msg.contentType == ContentType.handshake:
            b = msg.write()
            self._handshakeHashes.update(b)
        return super(TLSConnection, self).sendMessage(msg, randomizeFirstBlock)

    def _handshakeStart(self, client):
        if not self.closed:
            raise ValueError("Renegotiation disallowed for security reasons")
        self.client = client
        self._handshakeHashes = HandshakeHashes()
        self.allegedSrpUsername = None
        self._refCount = 1

    def _getMsg(self, expectedType, secondaryType=None, constructorType=None):
        try:
            if not isinstance(expectedType, tuple):
                expectedType = (expectedType,)

            #Spin in a loop, until we've got a non-empty record of a type we
            #expect.  The loop will be repeated if:
            #  - we receive a renegotiation attempt; we send no_renegotiation,
            #    then try again
            #  - we receive an empty application-data fragment; we try again
            while 1:
                for result in self.recvMessage():
                    if result in (0,1):
                        yield result
                    else: break
                recordHeader, p = result

                #If this is an empty application-data fragment, try again
                if recordHeader.type == ContentType.application_data:
                    if p.index == len(p.bytes):
                        continue

                #If we received an unexpected record type...
                if recordHeader.type not in expectedType:

                    #If we received an alert...
                    if recordHeader.type == ContentType.alert:
                        alert = Alert().parse(p)

                        #We either received a fatal error, a warning, or a
                        #close_notify.  In any case, we're going to close the
                        #connection.  In the latter two cases we respond with
                        #a close_notify, but ignore any socket errors, since
                        #the other side might have already closed the socket.
                        if alert.level == AlertLevel.warning or \
                           alert.description == AlertDescription.close_notify:

                            #If the sendMsg() call fails because the socket has
                            #already been closed, we will be forgiving and not
                            #report the error nor invalidate the "resumability"
                            #of the session.
                            try:
                                alertMsg = Alert()
                                alertMsg.create(AlertDescription.close_notify,
                                                AlertLevel.warning)
                                for result in self.sendMessage(alertMsg):
                                    yield result
                            except socket.error:
                                pass

                            if alert.description == \
                                   AlertDescription.close_notify:
                                self._shutdown(True)
                            elif alert.level == AlertLevel.warning:
                                self._shutdown(False)

                        else: #Fatal alert:
                            self._shutdown(False)

                        #Raise the alert as an exception
                        raise TLSRemoteAlert(alert)

                    #If we received a renegotiation attempt...
                    if recordHeader.type == ContentType.handshake:
                        subType = p.get(1)
                        reneg = False
                        if self.client:
                            if subType == HandshakeType.hello_request:
                                reneg = True
                        else:
                            if subType == HandshakeType.client_hello:
                                reneg = True
                        #Send no_renegotiation, then try again
                        if reneg:
                            alertMsg = Alert()
                            alertMsg.create(AlertDescription.no_renegotiation,
                                            AlertLevel.warning)
                            for result in self.sendMessage(alertMsg):
                                yield result
                            continue

                    #Otherwise: this is an unexpected record, but neither an
                    #alert nor renegotiation
                    for result in self._sendError(\
                            AlertDescription.unexpected_message,
                            "received type=%d" % recordHeader.type):
                        yield result

                break

            #Parse based on content_type
            if recordHeader.type == ContentType.change_cipher_spec:
                yield ChangeCipherSpec().parse(p)
            elif recordHeader.type == ContentType.alert:
                yield Alert().parse(p)
            elif recordHeader.type == ContentType.application_data:
                yield ApplicationData().parse(p)
            elif recordHeader.type == ContentType.handshake:
                #Convert secondaryType to tuple, if it isn't already
                if not isinstance(secondaryType, tuple):
                    secondaryType = (secondaryType,)

                #If it's a handshake message, check handshake header
                if recordHeader.ssl2:
                    subType = p.get(1)
                    if subType != HandshakeType.client_hello:
                        for result in self._sendError(\
                                AlertDescription.unexpected_message,
                                "Can only handle SSLv2 ClientHello messages"):
                            yield result
                    if HandshakeType.client_hello not in secondaryType:
                        for result in self._sendError(\
                                AlertDescription.unexpected_message):
                            yield result
                    subType = HandshakeType.client_hello
                else:
                    subType = p.get(1)
                    if subType not in secondaryType:
                        for result in self._sendError(\
                                AlertDescription.unexpected_message,
                                "Expecting %s, got %s" % (str(secondaryType), subType)):
                            yield result

                #Update handshake hashes
                self._handshakeHashes.update(p.bytes)

                #Parse based on handshake type
                if subType == HandshakeType.client_hello:
                    yield ClientHello(recordHeader.ssl2).parse(p)
                elif subType == HandshakeType.server_hello:
                    yield ServerHello().parse(p)
                elif subType == HandshakeType.certificate:
                    yield Certificate(constructorType).parse(p)
                elif subType == HandshakeType.certificate_request:
                    yield CertificateRequest(self.version).parse(p)
                elif subType == HandshakeType.certificate_verify:
                    yield CertificateVerify().parse(p)
                elif subType == HandshakeType.server_key_exchange:
                    yield ServerKeyExchange(constructorType).parse(p)
                elif subType == HandshakeType.server_hello_done:
                    yield ServerHelloDone().parse(p)
                elif subType == HandshakeType.client_key_exchange:
                    yield ClientKeyExchange(constructorType, \
                                            self.version).parse(p)
                elif subType == HandshakeType.finished:
                    yield Finished(self.version).parse(p)
                elif subType == HandshakeType.next_protocol:
                    yield NextProtocol().parse(p)
                else:
                    raise AssertionError()

        #If an exception was raised by a Parser or Message instance:
        except SyntaxError as e:
            for result in self._sendError(AlertDescription.decode_error,
                                         formatExceptionTrace(e)):
                yield result
