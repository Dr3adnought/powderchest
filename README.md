```mermaid graph TD
    subgraph Internet
        CF[Cloudflare: The Mist]
    end

    subgraph Pi4_Edge [The Crow's Nest: Raspberry Pi 4]
        Nginx[Nginx: Harbor Master]
        Web[Powderchest Dashboard]
    end

    subgraph Pi5_Compute [The Galleon: Raspberry Pi 5]
        Docker[Docker Engine]
        subgraph Containers [The Crew]
            MC[Minecraft Servers]
            PH[Pi-Hole / Unbound]
            WG[WireGuard]
            OL[Ollama AI]
        end
        BM[BlueMap Renderer]
    end

    subgraph Storage [The Treasure Chest]
        SSD[(Samba SSD)]
    end

    %% Connections
    CF <--> Nginx
    Nginx <--> Web
    Web <--> BM
    Docker --- Containers
    Containers --- SSD
    BM --- SSD
    MC --- BM
    classDef edgeNode fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#fff;
    classDef computeNode fill:#1a2e05,stroke:#4d7c0f,stroke-width:2px,color:#fff;
    classDef storageNode fill:#422006,stroke:#b45309,stroke-width:2px,color:#fff;

    class Pi4_Edge edgeNode;
    class Pi5_Compute computeNode;
    class Storage storageNode;```