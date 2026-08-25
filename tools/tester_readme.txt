RotoBridge @VERSION@
====================

Moves roto splines between After Effects and Nuke.

You need only the half you use. Installing both on one machine is fine.


AFTER EFFECTS
-------------

1. Put the "after_effects" folder anywhere you like and keep it together -
   the one script in it needs the "lib" folder beside it.

2. Turn this preference ON, then restart After Effects:

       Edit > Preferences > Scripting & Expressions >
       Allow Scripts to Write Files and Access Network

   It is off in a fresh install and nothing works without it. RotoBridge will
   tell you if it is off, but it saves a round trip to just do it now.

3. File > Scripts > Run Script File...  and pick

       after_effects\rotobridge_panel.jsx

   A small RotoBridge window opens with two buttons. That is the whole thing.
   You do this each time you start After Effects - there is nothing installed
   and nothing to uninstall.

To export: select the layers holding the masks you want, then Export.
To import: open the comp you want the shapes in, then Import.


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
