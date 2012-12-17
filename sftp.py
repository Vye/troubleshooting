from os.path import basename
import sys

from twisted.conch.client.connect import connect
from twisted.conch.client.options import ConchOptions
from twisted.internet.defer import Deferred
from twisted.conch.ssh import channel, userauth
from twisted.conch.ssh.common import NS
from twisted.conch.ssh.connection import SSHConnection
from twisted.conch.ssh.filetransfer import FXF_WRITE, FXF_CREAT, \
    FXF_TRUNC, FileTransferClient
from twisted.internet import reactor, defer
from twisted.python.log import startLogging


ACTIVE_CLIENTS = {}
USERNAME = 'user'           # change me!
PASSWORD = 'password'       # change me!
HOST = ('hostname', 22)     # change me!
TEST_FILE_PATH = __file__
TEST_FILE_NAME = basename(__file__)


def openSFTP(user, host):
    conn = SFTPConnection()
    options = ConchOptions()
    options['host'], options['port'] = host
    conn._sftp = Deferred()
    auth = SimpleUserAuth(user, conn)
    connect(options['host'], options['port'], options, verifyHostKey, auth)
    return conn._sftp


def verifyHostKey(ui, hostname, ip, key):
    return defer.succeed(True)


class SimpleUserAuth(userauth.SSHUserAuthClient):
    def getPassword(self):
        return defer.succeed(PASSWORD)


class SFTPConnection(SSHConnection):
    def serviceStarted(self):
        self.openChannel(SFTPChannel())


class SFTPChannel(channel.SSHChannel):
    name = 'session'

    def channelOpen(self, ignoredData):
        d = self.conn.sendRequest(self, 'subsystem', NS('sftp'),
                                  wantReply=True)
        d.addCallback(self._cbFTP)
        d.addErrback(self.printErr)

    def _cbFTP(self, ignore):
        client = FileTransferClient()
        client.makeConnection(self)
        self.dataReceived = client.dataReceived
        ACTIVE_CLIENTS.update({self.conn.transport.transport.addr: client})
        self.conn._sftp.callback(None)

    def printErr(self, msg):
        print msg
        return msg


@defer.inlineCallbacks
def main():
    d = openSFTP(USERNAME, HOST)
    _ = yield d

    client = ACTIVE_CLIENTS[HOST]
    d = client.openFile(TEST_FILE_NAME, FXF_WRITE | FXF_CREAT | FXF_TRUNC, {})
    df = yield d

    sf = open(TEST_FILE_PATH, 'rb')
    d = df.writeChunk(0, sf.read())
    _ = yield d

    sf.close()
    d = df.close()
    _ = yield d

    ACTIVE_CLIENTS[HOST].transport.loseConnection()
    # loseConnection() call above causes the following log messages:
    # [SSHChannel session (0) on SSHService ssh-connection on SSHClientTransport,client] sending close 0
    # [SSHChannel session (0) on SSHService ssh-connection on SSHClientTransport,client] unhandled request for exit-status
    # [SSHChannel session (0) on SSHService ssh-connection on SSHClientTransport,client] remote close
    # [SSHChannel session (0) on SSHService ssh-connection on SSHClientTransport,client] closed
    # I can see the channel closed on the server side:
    # sshd[4485]: debug1: session_exit_message: session 0 channel 0 pid 4486
    # sshd[4485]: debug1: session_exit_message: release channel 0
    # sshd[4485]: debug1: session_by_channel: session 0 channel 0

    ACTIVE_CLIENTS[HOST].transport.conn.transport.loseConnection()
    # loseConnection() call above does not close the SSH connection.

    reactor.callLater(5, reactor.stop)
    # Stopping the reactor closes the SSH connection and logs the following messages:
    # [SSHClientTransport,client] connection lost
    # [SSHClientTransport,client] Stopping factory <twisted.conch.client.direct.SSHClientFactory instance at 0x02E5AF30>
    # [-] Main loop terminated.
    # On the server side:
    # sshd[4485]: Closing connection to xxx.xxx.xxx.xxx


if __name__ == '__main__':
    startLogging(sys.stdout)
    reactor.callWhenRunning(main)
    reactor.run()
