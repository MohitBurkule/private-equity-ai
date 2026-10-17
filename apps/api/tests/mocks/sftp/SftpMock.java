// Dev/test SFTP server built on Apache MINA SSHD (github.com/apache/mina-sshd), run from its jars.
// Usage: java -cp <sshd jars> SftpMock <port> <root dir> <user> <password>
// Serves <root dir> as the SFTP root for one account. Test use only; never run this against real data.
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

import org.apache.sshd.common.file.virtualfs.VirtualFileSystemFactory;
import org.apache.sshd.server.SshServer;
import org.apache.sshd.server.keyprovider.SimpleGeneratorHostKeyProvider;
import org.apache.sshd.sftp.server.SftpSubsystemFactory;

public class SftpMock {
    public static void main(String[] args) throws Exception {
        int port = Integer.parseInt(args[0]);
        Path root = Paths.get(args[1]);
        String user = args[2];
        String password = args[3];

        SshServer server = SshServer.setUpDefaultServer();
        server.setPort(port);
        server.setKeyPairProvider(new SimpleGeneratorHostKeyProvider(root.resolveSibling("sftp-host.ser")));
        server.setPasswordAuthenticator((u, p, session) -> user.equals(u) && password.equals(p));
        server.setPublickeyAuthenticator((u, key, session) -> false);
        server.setSubsystemFactories(List.of(new SftpSubsystemFactory()));
        server.setFileSystemFactory(new VirtualFileSystemFactory(root));
        server.start();
        System.out.println("READY " + port);
        Thread.currentThread().join();
    }
}
