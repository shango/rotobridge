RotoBridge @VERSION@
====================

Moves roto splines between After Effects and Nuke.

You need only the half you use. Installing both on one machine is fine.


AFTER EFFECTS
-------------

1. Turn this preference ON, then restart After Effects:

       Edit > Preferences > Scripting & Expressions >
       Allow Scripts to Write Files and Access Network

   It is off in a fresh install and nothing works without it - not even the
   installer, which will tell you so.

2. Unzip the download, then File > Scripts > Run Script File...  and pick

       after_effects\Install for After Effects.jsx

   That is the last time you browse for a script. It copies RotoBridge into
   your own After Effects user folder - no administrator password, nothing
   outside your user folder - and says what it did.

3. Restart After Effects. RotoBridge is now in the menu:

       Window > RotoBridge.jsx

   A small panel with two buttons that docks like any other. Updating to a
   later build is the same two steps: run the new download's installer,
   restart.

To export: select the layers holding the masks you want, then Export.
To import: open the comp you want the shapes in, then Import.


WHERE FILES GO
--------------

Once your project is saved, both applications offer the same place by
default: a "rotobridge" folder next to the project file (.aep or .nk).
Export accepts it with one click, and import opens on the newest .rbj in
it, so the usual round trip never types a path. Every dialog still lets
you point anywhere else.


NUKE
----

1. Close Nuke.

2. Double-click

       nuke\Install for Nuke.bat

   It copies RotoBridge into your own .nuke folder. No administrator password,
   nothing outside your user folder.

3. Start Nuke. There is a RotoBridge menu in the menu bar.

To export: select a Roto node, then RotoBridge > Export to .rbj.
To import: RotoBridge > Import .rbj. It builds a new Roto node.


REPORTING A BUG
---------------

Every RotoBridge window says which version it is, including the error ones.
A screenshot of the window is enough to start with - please do not crop the
version off.

For anything about an IMPORT going wrong, there is something better. Every
import writes a plain text file next to your project, named after it and
ending ".rotobridge.txt". Send me that file. It records what came in, what
settings were used, how far the result sits from the original, and every
warning - so it usually answers the question without a back-and-forth.

If you cannot find your version: in Nuke it is under RotoBridge > About. In
After Effects it is along the bottom of the panel.


KNOWN AND EXPECTED
------------------

Warnings are not errors. When something genuinely cannot cross between the two
applications, RotoBridge says so in a warning rather than dropping it quietly.
Seeing warnings on a complex shape is normal. Please still send them - which
warnings show up on real work is one of the things this test is for.
